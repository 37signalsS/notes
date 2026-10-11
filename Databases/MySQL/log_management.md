# Управление логами MySQL: error, slow, general, binlog

**Актуально для:** MySQL 8.4 LTS (8.4.12, 2026-08-18). MySQL 8.0 достиг EOL 21 апреля 2026 года — без патчей безопасности, переходите на 8.4 LTS или 9.7 LTS.

## Определения

*   **Error Log** — журнал ошибок сервера: запуск/остановка, ошибки InnoDB, дедлоки (`LATEST DETECTED DEADLOCK` при `innodb_print_all_deadlocks`), ошибки репликации, предупреждения. Первый источник при диагностике инцидентов.
*   **`log_error_verbosity`** — уровень детализации error log (MySQL 8.0+). `0` или `OFF` — отключить; `1` — только ошибки; `2` — ошибки и предупреждения (по умолчанию); `3` — ошибки, предупреждения и заметки (notes).
*   **Slow Query Log** — журнал запросов, превысивших `long_query_time`. Основа для `pt-query-digest` и оптимизации.
*   **General Query Log** — журнал всех запросов (включая подключения). Тяжёлый, в production держится выключенным.
*   **Binary Log (Binlog)** — журнал изменений данных (DDL/DML). Основа репликации и PITR. Ротируется по `binlog_expire_logs_seconds`.
*   **Relay Log** — бинарный лог реплики, полученный от источника. Ротируется автоматически.
*   **`log_output`** — куда пишутся slow/general логи: `FILE` (по умолчанию) или `TABLE` (`mysql.slow_log`, `mysql.general_log`).

## Предварительные требования

*   **Права пользователя для logrotate:** скрипт `postrotate` вызывает `mysqladmin flush-logs` или `mysql -e "FLUSH LOGS"`, что требует привилегии `RELOAD`. Создайте выделенного пользователя с минимальными правами или используйте `~/.my.cnf` с правами `RELOAD`:
    ```sql
    CREATE USER 'logrotate'@'localhost' IDENTIFIED BY 'StrongPassword!';
    GRANT RELOAD, PROCESS ON *.* TO 'logrotate'@'localhost';
    FLUSH PRIVILEGES;
    ```
*   **Права на каталог логов:** `/var/log/mysql/` должен принадлежать пользователю `mysql`, с правами `0750`:
    ```bash
    sudo mkdir -p /var/log/mysql
    sudo chown mysql:mysql /var/log/mysql
    sudo chmod 0750 /var/log/mysql
    ```
*   **SELinux:** если SELinux включён, установите контекст `mysqld_log_t` на каталог логов:
    ```bash
    sudo semanage fcontext -a -t mysqld_log_t "/var/log/mysql(/.*)?"
    sudo restorecon -Rv /var/log/mysql
    ```
*   **AppArmor:** если профиль AppArmor активен, убедитесь, что путь к логам включён в профиль (`/etc/apparmor.d/usr.sbin.mysqld`).
*   **Свободное место:** для файловых логов рекомендуется отдельный том или VFS-каталог с мониторингом `df -h`. Минимум 20–30% свободного места для logrotate и binlog-ротации.
*   **logrotate:** убедитесь, что `logrotate` и таймер/крон активны: `systemctl status logrotate.timer`.

## Базовые концепции

### Четыре лога и их назначение

| Лог | Переменная | По умолчанию | Назначение | Ротация |
| :--- | :--- | :--- | :--- | :--- |
| Error | `log_error` | ON (файл в datadir) | Ошибки, дедлоки, инциденты | logrotate |
| Slow | `slow_query_log` | OFF | Медленные запросы | `FLUSH LOGS` / logrotate |
| General | `general_log` | OFF | Все запросы (debug) | logrotate |
| Binlog | `log_bin` | ON (8.0+) | Репликация, PITR | `binlog_expire_logs_seconds` |

### Error Log — что искать

*   `InnoDB: Corruption in page` — повреждение страниц.
*   `LATEST DETECTED DEADLOCK` — дедлоки (при `innodb_print_all_deadlocks = ON`).
*   `[ERROR] Slave SQL: ...` — ошибки применения репликации.
*   `InnoDB: Failing to set up MTR` — повреждение redo log.
*   `Table '...' is marked as crashed` — сбой MyISAM.
*   `Plugin 'InnoDB' init function returned error` — ошибка инициализации.

### Slow Query Log — параметры

```ini
[mysqld]
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow-query.log
long_query_time = 1.0              # порог, сек (дефолт 10 — ставьте 1)
log_slow_admin_statements = ON     # ALTER, ANALYZE, CHECK, CREATE INDEX...
log_slow_replica_statements = ON   # медленные запросы на реплике (8.0.26+)
log_slow_extra = ON                # доп. поля: thread_id, schema, rows_affected (8.0.14+)
log_min_examined_row_limit = 1000  # отсекает тривиальные запросы (меньше 1000 строк)
log_output = FILE                  # FILE или TABLE
```

**Важно:** `log_slow_replica_statements` не работает при `binlog_format = ROW` — запросы на реплике не попадают в slow log, так как применяются через SQL-поток.

### Error Log — управление через systemd и journald

В MySQL 8.0+ error log можно направлять не только в файл, но и в `systemd journal`, `syslog`, либо в `stderr` (для контейнеров):

```ini
[mysqld]
# Явный путь к файлу error log
log_error = /var/log/mysql/error.log
log_error_verbosity = 2            # 1=errors, 2=errors+warnings (default), 3=all

# Альтернатива: вывод в stderr (для контейнеров и systemd)
# log_error = stderr               # выводит в stderr, systemd/journald ловит сам
# log_error_verbosity = 2
```

```bash
# Просмотр error log через journald (MySQL 8.0+ с systemd)
journalctl -u mysql --since "1 hour ago" -p warning

# Ротация через journald (не требует logrotate)
# В /etc/systemd/journald.conf:
# [Journal]
# SystemMaxUse=500M
# MaxRetentionSec=14d
```

**Динамическое управление** (без рестарта, MySQL 8.0+):

```sql
-- Изменить уровень детализации error log и сохранить в mysqld-auto.cnf
SET PERSIST log_error_verbosity = 3;

-- Включить slow query log динамически и сохранить
SET PERSIST slow_query_log = ON;
SET PERSIST long_query_time = 0.5;

-- Просмотр сохранённых настроек
SELECT * FROM performance_schema.persisted_variables;
```

### General Log — когда включать

General log пишет **все** запросы. Включайте только на время debug (утечки соединений, подозрительная активность), затем выключайте — он быстро растёт и нагружает диск.

```sql
SET GLOBAL general_log = ON;
-- debug...
SET GLOBAL general_log = OFF;
```

## Практические сценарии

### 1. Настройка error log

```ini
[mysqld]
log_error = /var/log/mysql/error.log
log_error_verbosity = 2            # 1=errors, 2=errors+warnings (default), 3=all
# Полная история дедлоков в error log (production)
innodb_print_all_deadlocks = ON
# Периодический вывод состояния InnoDB в error log (для постоянной диагностики)
# innodb_status_output = ON          # каждые ~15 секунд (включать только на время)
# innodb_status_output_locks = ON    # + информация о блокировках (увеличивает объём)
```

```bash
# Текущий error log
mysql -e "SHOW VARIABLES LIKE 'log_error';"
# → /var/log/mysql/error.log

# Дедлоки за период
grep -c "LATEST DETECTED DEADLOCK" /var/log/mysql/error.log

# Ротация error log через logrotate
cat > /etc/logrotate.d/mysql-error << 'EOF'
/var/log/mysql/error.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    create 640 mysql adm
    sharedscripts
    postrotate
        mysqladmin --defaults-file=/root/.my.cnf flush-logs > /dev/null 2>&1 || true
    endscript
}
EOF
# → конфигурация создана
```

### 2. Ротация slow log через logrotate

```bash
cat > /etc/logrotate.d/mysql-slow << 'EOF'
/var/log/mysql/slow-query.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 640 mysql mysql
    postrotate
        mysql -e "FLUSH SLOW LOGS;"
    endscript
}
EOF
```

**Важно:** `FLUSH SLOW LOGS` (или `FLUSH LOGS`) обязателен в `postrotate` — иначе MySQL продолжает писать в уже переименованный файл (дескриптор открыт). Без него логи теряются.

### 3. Ротация binlog

```ini
[mysqld]
# Автоочистка binlog (дефолт 30 дней; для PITR — больше RPO + запас)
binlog_expire_logs_seconds = 604800   # 7 дней
```

```sql
-- Ручная ротация (создаёт новый binlog-файл)
FLUSH BINARY LOGS;

-- Очистка binlog до указанной позиции
PURGE BINARY LOGS BEFORE NOW() - INTERVAL 7 DAY;

-- Проверка
SHOW BINARY LOGS;
```

**Важно:** `binlog_expire_logs_seconds` должен быть больше максимального простоя любой реплики — иначе реплика, простоявшая дольше срока, не сможет догнать (ошибка 1789, purged GTID).

### 4. Анализ slow log

```bash
# Топ-15 медленных запросов
pt-query-digest --limit 15 /var/log/mysql/slow-query.log

# Сравнение до/после оптимизации
pt-query-digest --output /tmp/qd_before.txt /var/log/mysql/slow-query.log
# ... оптимизация ...
pt-query-digest --output /tmp/qd_after.txt /var/log/mysql/slow-query.log
```

### 5. Переключение slow log на другой файл (без рестарта)

```sql
SET GLOBAL slow_query_log_file = '/var/log/mysql/slow-query.log.new';
SET GLOBAL slow_query_log = OFF;
SET GLOBAL slow_query_log = ON;
```

## Устранение неисправностей (Troubleshooting)

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Slow log пуст | `slow_query_log = OFF` или `long_query_time` высокий | Включить, `long_query_time = 1.0` |
| Slow log растёт быстро | Много медленных запросов или низкий порог | `pt-query-digest`, оптимизация; `long_query_time` выше |
| Error log не пишется | Нет прав на каталог | `chown mysql:mysql /var/log/mysql` |
| Binlog переполняет диск | `binlog_expire_logs_seconds` велик или реплики отстали | Уменьшить срок; проверить лаг реплик |
| logrotate не работает | Нет `FLUSH LOGS` в postrotate | Добавить `mysql -e "FLUSH SLOW LOGS;"` |
| General log заполнил диск | Оставлен включённым после debug | `SET GLOBAL general_log = OFF` |

### Метки времени в логах

```ini
[mysqld]
# UTC для единообразия (важно при анализе логов из разных ЦОД)
log_timestamps = UTC
```

**Важно:** в MySQL 8.4 LTS переменная `log_timestamps` управляет временными метками во **всех** логах (error, slow, general). По умолчанию `UTC`. При анализе логов из разных источников убедитесь, что все серверы используют один часовой пояс — иначе сопоставить события невозможно.

## Мониторинг и валидация (DevOps / SRE)

### Метрики и алертинг

Для непрерывного наблюдения за логами настраивайте алерты на ключевые сигналы:

| Метрика | Источник | Порог | Действие |
| :--- | :--- | :--- | :--- |
| Disk usage `/var/log/mysql/` | `df -h` / node_exporter | > 80% | Уменьшить `binlog_expire_logs_seconds`, проверить лаг реплик |
| Slow queries (прирост/мин) | `SHOW GLOBAL STATUS` | > 50–100/мин | Анализировать `pt-query-digest` за окном |
| Error log: новые ERROR/WARNING | `journalctl -u mysql -p err` | > 0 за 5 мин | Автоматический парсинг `grep -i error` |
| General log включён | `SHOW VARIABLES LIKE 'general_log'` | ON в production | Аварийно выключить: `SET GLOBAL general_log = OFF` |
| Binlog file count | `SHOW BINARY LOGS` | рост > 50 файлов/день | Проверить репликацию, уменьшить retention |

**Пример алерта (Prometheus + mysqld_exporter):**

```yaml
- alert: MySQLLogDiskFull
  expr: node_filesystem_avail_bytes{mountpoint="/var/log/mysql"} / node_filesystem_size_bytes{mountpoint="/var/log/mysql"} * 100 < 20
  for: 5m
  annotations:
    summary: "MySQL: <20% свободного места под логи"
    runbook: "Уменьшить binlog_expire_logs_seconds, проверить relay_log_purge, почистить general log"

- alert: MySQLSlowQuerySpike
  expr: rate(mysql_global_status_slow_queries[5m]) > 1
  for: 10m
  annotations:
    summary: "MySQL: > 1 slow query/сек ({{ $value | humanize }}/s)"
```

### Валидация конфигурации

**Перед рестартом сервера:**

```bash
# Проверка синтаксиса my.cnf
sudo mysqld --validate-config
# → пустой вывод = ошибок нет

# Проверка, что пути существуют
sudo -u mysql touch /var/log/mysql/slow-query.log && sudo chown mysql:mysql /var/log/mysql/slow-query.log
```

**После применения изменений:**

```sql
-- Проверка переменных логирования
SHOW VARIABLES LIKE 'log_error';
SHOW VARIABLES LIKE 'log_error_verbosity';
SHOW VARIABLES LIKE 'slow_query_log%';
SHOW VARIABLES LIKE 'general_log';
SHOW VARIABLES LIKE 'log_output';
SHOW VARIABLES LIKE 'log_timestamps';
SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';
```

```bash
# Проверка, что файл лога доступен для записи пользователю mysql
mysql -N -B -e "SELECT @@slow_query_log_file;" | xargs ls -la
# → -rw-r----- 1 mysql mysql ... /var/log/mysql/slow-query.log

# Проверка ротации
logrotate -d /etc/logrotate.d/mysql-slow
# → "considering log /var/log/mysql/slow-query.log" без ошибок
```

**Проверка, что slow log пишется:**

```sql
SET SESSION long_query_time = 0;
SELECT SLEEP(2);
SET SESSION long_query_time = 1.0;
SHOW GLOBAL STATUS LIKE 'Slow_queries';
-- → значение выросло на 1
```

> **Осторожно:** `SET SESSION long_query_time = 0` логирует всё, включая внутренние запросы мониторинга. Возвращайте значение сразу.

## Лучшие практики

1.  **Error log — первый источник** при любом инциденте; держите ротацию и хранение истории.
2.  **`innodb_print_all_deadlocks = ON`** в production — полная история дедлоков.
3.  **`long_query_time = 1.0`** — ловите запросы > 1 сек, не > 10.
4.  **`log_min_examined_row_limit`** — отсекает тривиальные запросы, не проникающие в slow log.
5.  **`FLUSH LOGS` в postrotate** — иначе логи теряются.
6.  **`binlog_expire_logs_seconds` > max replica downtime** — иначе реплика не догонит.
7.  **General log — только на время debug**, затем выключать.
8.  **`log_timestamps = UTC`** — единообразие при мульти-ЦОД.
9.  **`log_error_verbosity = 2`** в production (не 3 — notes сильно увеличивают объём).
10. **Не ротируйте binlog через logrotate** — только через `PURGE`/`binlog_expire_logs_seconds`.

### Очистка и откат

*   Отключить general log: `SET PERSIST general_log = OFF;` или закомментировать в `my.cnf`.
*   Очистить табличный slow/general log: `TRUNCATE TABLE mysql.slow_log; TRUNCATE TABLE mysql.general_log;`
*   Отключить `innodb_status_output`: `SET GLOBAL innodb_status_output = OFF; SET GLOBAL innodb_status_output_locks = OFF;`
*   Проверить, что logrotate активен: `systemctl status logrotate.timer` или `systemctl list-timers | grep logrotate`.
*   Удалить конфиг logrotate: `rm /etc/logrotate.d/mysql-slow /etc/logrotate.d/mysql-error` (только если ротация больше не нужна).
*   Очистить старые логи: `find /var/log/mysql/ -name "*.log.*" -mtime +30 -delete` (осторожно! не удаляйте binlog таким способом).

### Граничные случаи (Edge Cases)

*   **`log_output = TABLE`:** таблицы `mysql.slow_log` и `mysql.general_log` растут бесконецно. Настраивайте периодический `TRUNCATE TABLE` через cron.
*   **`copytruncate` vs `postrotate`:** `copytruncate` проще (не требует `FLUSH`), но может потерять записи между копированием и обрезкой. `postrotate` + `FLUSH LOGS` надёжнее, но требует привилегий `RELOAD`.
*   **SELinux/AppArmor:** при смене пути логов (`/var/log/mysql` → `/data/logs`) обновите SELinux контекст (`semanage fcontext -a -t mysqld_log_t`) и профиль AppArmor (`/etc/apparmor.d/usr.sbin.mysqld`).
*   **Binlog на datadir:** если binlog не вынесен на отдельный диск, `PURGE` не освобождает место из-за файловой системы (особенно ZFS с `recordsize`).
*   **Многопоточная ротация:** logrotate с `sharedscripts` гарантирует один `postrotate` для всех файлов в блоке — критично при ротации error + slow + general log совместно.
*   **Container stderr:** в Docker/Kubernetes error log в `stderr` собирает runtime; `log_timestamps` и `log_error_verbosity` всё равно применяются к содержимому.
*   **Мульти-инстанс (systemd):** для нескольких экземпляров MySQL на одном хосте (`mysqld@.service`) используйте разные `log_error` и `log_bin_basename` на каждом экземпляре.

## Дополнительная информация

### См. также

*   **[Анализ медленных запросов](Operations/slow-query-analysis.md)** — pt-query-digest, пороги, валидация.
*   **[Мониторинг](monitoring.md)** — slow queries метрики, алертинг.
*   **[Binlog: управление](replication/binlog_management.md)** — ротация, purge.
*   **[PITR](backup_and_recovery/pitr.md)** — восстановление из binlog.
*   **[logrotate (Linux)](../../Linux/SystemAdministration/Logging/logrotate.md)** — теория и конфигурация logrotate.
*   **[MariaDB: управление логами](../MariaDB/log_management.md)** — аналог для MariaDB.

### Внешние ресурсы

*   [MySQL Error Log](https://dev.mysql.com/doc/refman/8.4/en/error-log.html)
*   [MySQL Slow Query Log](https://dev.mysql.com/doc/refman/8.4/en/slow-query-log.html)
*   [MySQL Binary Log](https://dev.mysql.com/doc/refman/8.4/en/binary-log.html)
