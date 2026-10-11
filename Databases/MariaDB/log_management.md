# Управление логами MariaDB и logrotate

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Error Log** — лог ошибок сервера: запуск/остановка, критические ошибки, crash, corruption. Управляется системной переменной `log_error` (путь к файлу, либо `syslog`/`journald`). В отличие от MySQL, MariaDB не использует `log_error_verbosity` — уровень детализации регулируется переменной `log_warnings`.
*   **SQL Error Log Plugin** — отдельный плагин (`sql_errlog`), логирующий ошибки, отправленные клиентам (OS error codes, синтаксис и т.п.). Не установлен по умолчанию. Управляется переменными: `sql_error_log_filename`, `sql_error_log_rotate`, `sql_error_log_rotations`, `sql_error_log_size_limit`, `sql_error_log_warnings` (MariaDB 10.11.5+), `sql_error_log_rate`. В отличие от error log, этот плагин ротирует лог автоматически по размеру.
*   **Slow Query Log** — лог запросов, превышающих `long_query_time`. Основной источник для оптимизации. Может писать в файл или таблицу (`mysql.slow_log`).
*   **General Query Log** — лог всех запросов (включая SELECT). Отключён по умолчанию — включать только для диагностики (высокая нагрузка, риск утечки данных).
*   **Binary Log (binlog)** — журнал изменений данных (репликация + PITR). Ротируется через `FLUSH BINARY LOGS` / `PURGE BINARY LOGS` / `binlog_expire_logs_seconds`. Подробнее: **[Бинарное логирование](security/binary-logging.md)**.
*   **Relay Log** — журнал на реплике с событиями от source. Ротируется автоматически.
*   **`log_warnings`** — системная переменная (0–9): регулирует verbosity error log. По умолчанию `2`. Заменяет MySQL-переменную `log_error_verbosity` (MariaDB её не поддерживает).
*   **`log_output`** — системная переменная (`FILE` / `TABLE`): выбирает, куда писать slow/general query log. По умолчанию `FILE`.
*   **logrotate** — утилита Linux для ротации, сжатия и удаления старых лог-файлов. Конфигурация: `/etc/logrotate.d/`. Подробнее: **[logrotate](../../Linux/SystemAdministration/Logging/logrotate.md)**.
*   **`FLUSH LOGS` / `FLUSH ERROR`** — SQL-команда закрытия и переоткрытия лог-файлов. `FLUSH ERROR LOGS` — только error log; `FLUSH [ENGINE|GENERAL|SLOW|RELAY] LOGS` — указанные логи; `FLUSH BINARY LOGS` — ротация binlog.

## Предварительные требования

*   **Права пользователя для logrotate:** скрипт `postrotate` вызывает `mariadb-admin flush-logs`, что требует привилегии `RELOAD`. Проще всего создать пользователя `root@localhost` с аутентификацией через unix socket, либо использовать `--defaults-file=/root/.my.cnf` с правами `RELOAD` + `SUPER`.
*   **Права на каталог логов:** `/var/log/mysql/` должен принадлежать пользователю `mysql`, с правами `0750` (или `0770` с группой `mysql` для совместного доступа).
*   **SELinux:** если SELinux включён, установите контекст `mysqld_log_t` на каталог логов (`semanage fcontext -a -t mysqld_log_t "/var/log/mysql(/.*)?"`) и примените `restorecon -Rv /var/log/mysql`.
*   **Свободное место:** для файловых логов рекомендуется отдельный том/VFS-каталог с мониторингом `df -h`.

## Базовые концепции

### Типы логов и их ротация

| Лог | По умолчанию | Ротация | Механизм | `log_output` |
| :--- | :--- | :--- | :--- | :--- |
| **Error Log** | Вкл. | logrotate или `FLUSH ERROR` | Файл или journald/syslog | N/A |
| **Slow Query Log** | Выкл. | logrotate или `FLUSH SLOW LOGS` | Файл или таблица | `FILE` / `TABLE` |
| **General Query Log** | Выкл. | logrotate или `FLUSH GENERAL LOGS` | Файл или таблица | `FILE` / `TABLE` |
| **SQL Error Log Plugin** | Выкл. | Автоматически (по размеру) | Файл | N/A |
| **Binary Log** | Вкл. (при репликации) | `FLUSH BINARY LOGS`, `PURGE BINARY LOGS`, `binlog_expire_logs_seconds` | Автоматически | N/A |
| **Relay Log** | Вкл. (на реплике) | Автоматически | Автоматически | N/A |

### Стратегия ротации

*   **Error/Slow/General logs (FILE):** ротируются через logrotate с `postrotate` + `FLUSH LOGS` или `copytruncate`.
*   **Slow/General logs (TABLE):** ротируются через `TRUNCATE TABLE mysql.slow_log` / `mysql.general_log`.
*   **Binary log:** НЕ ротируйте через logrotate — используйте `PURGE BINARY LOGS` / `binlog_expire_logs_seconds`. logrotate на binlog сломает репликацию и PITR.
*   **Relay log:** ротируется автоматически сервером.
*   **SQL Error Log Plugin:** ротируется автоматически по достижении `sql_error_log_size_limit`.

### `copytruncate` vs `postrotate`

*   **`copytruncate`:** копирует файл, затем обрезает оригинал. Просто, но возможна потеря записей между копированием и обрезкой (race condition). Не требует `FLUSH`.
*   **`postrotate` + `FLUSH LOGS`:** сначала `FLUSH LOGS` (сервер закрывает и переоткрывает файл), затем ротация. Надёжнее, но требует привилегий для `FLUSH`.

### Уровни детализности error log (`log_warnings`)

| Значение | Описание |
| :--- | :--- |
| `0` | Минимум: только обязательные предупреждения (core warnings всегда пишутся) |
| `1` | + репликационные сообщения, DNS lookup failures, event scheduler, unsafe statements |
| `2` (по умолчанию) | + access denied, aborted connections, table handler errors, replication state messages, binlog dump thread |
| `3` | + old-style language options, InnoDB online DDL progress |
| `4` | + killed connections, released connections |
| `9` | + подробности инициализации плагинов |

## Практические сценарии

### 1. Настройка логов в my.cnf

```ini
[mariadb]
# Error log (всегда включён)
log_error = /var/log/mysql/mariadb.log
log_warnings = 2

# Slow query log
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 0.5
log_slow_verbosity = query_plan,explain,engine
log_queries_not_using_indexes = ON

# General query log (только для диагностики!)
# general_log = 1
# general_log_file = /var/log/mysql/general.log
```

> **Важно:** `log_slow_extra` и `log_error_verbosity` — переменные MySQL 8.0+, **не поддерживаются** в MariaDB.

### 2. Ротация через logrotate (error + slow log)

Создайте `/etc/logrotate.d/mariadb`:

```
/var/log/mysql/mariadb.log
/var/log/mysql/slow.log
/var/log/mysql/general.log
{
    su mysql mysql
    missingok
    notifempty
    daily
    minsize 1M
    maxsize 100M
    rotate 30
    compress
    delaycompress
    olddir /var/log/mysql/archive/
    createolddir 770 mysql mysql
    create 640 mysql adm
    sharedscripts
    postrotate
        if [ -x /usr/bin/mariadb-admin ] && \
           /usr/bin/mariadb-admin --defaults-file=/root/.my.cnf ping >/dev/null 2>&1; then
            /usr/bin/mariadb-admin --local flush-error-log \
               flush-engine-log flush-general-log flush-slow-log
        fi
    endscript
}
```

Если каталог `archive/` не существует, создайте его вручную:

```bash
sudo mkdir -p /var/log/mysql/archive/
sudo chown mysql:mysql /var/log/mysql/archive/
sudo chmod 0770 /var/log/mysql/archive/
```

**Проверка конфигурации:**

```bash
# Синтаксическая проверка
logrotate -d /etc/logrotate.d/mariadb

# Принудительный запуск
logrotate -f /etc/logrotate.d/mariadb
```

**Валидация:** после ротации в `/var/log/mysql/` появятся `mariadb.log.1` (или `.1.gz` при `delaycompress`), а текущий `mariadb.log` — пустой с правильным владельцем.

### 3. Альтернатива: `copytruncate` (без FLUSH)

```
/var/log/mysql/mariadb.log
/var/log/mysql/slow.log
{
    su mysql mysql
    missingok
    notifempty
    daily
    minsize 1M
    maxsize 100M
    rotate 14
    compress
    delaycompress
    copytruncate
}
```

**Когда использовать:** если `mariadb-admin` недоступен. Минус: возможна потеря записей между `copy` и `truncate` (обычно микросекунды, но возможна в高并发场景).

### 4. Ротация binary log (НЕ через logrotate)

```sql
-- Автоматическая очистка binlog старше N секунд
SET GLOBAL binlog_expire_logs_seconds = 604800;  -- 7 дней

-- Ротация binlog (создать новый сегмент)
FLUSH BINARY LOGS;

-- Удалить binlog до указанной даты (только если реплики прочитали!)
PURGE BINARY LOGS BEFORE '2026-09-27 00:00:00';

-- Удалить до конкретного файла
PURGE BINARY LOGS TO 'mariadb-bin.000010';

-- Проверить статус binlog
SHOW BINARY LOGS;
```

```ini
[mariadb]
binlog_expire_logs_seconds = 604800
```

### 5. Ротация relay log

Relay log ротируется автоматически сервером. Для принудительной ротации:

```sql
-- На реплике
FLUSH RELAY LOGS;

-- Для multi-source: конкретный канал
FLUSH RELAY LOGS 'channel_name';
```

### 6. Логи в journald (systemd)

Для общего управления systemd см. **[MariaDB под systemd](systemd.md)**.

Если `log_error` не задан, либо задан `log_error=syslog` или `log_error=journal`:

```bash
# Просмотр логов MariaDB
journalctl -u mariadb --since "1 hour ago"

# Фильтр по уровню серьёзности
journalctl -u mariadb -p err
journalctl -u mariadb -p warning

# Ротация journald
journalctl --vacuum-time=14d
journalctl --vacuum-size=500M
```

```ini
# /etc/systemd/journald.conf
[Journal]
SystemMaxUse=500M
MaxRetentionSec=14day
```

### 7. SQL Error Log Plugin

Плагин `sql_errlog` логирует ошибки, отправленные клиентам (OS errors, ошибки синтаксиса), — их **нет** в error log. Лог автоматически ротируется при достижении `sql_error_log_size_limit`.

```sql
-- Установить плагин (до перезапуска)
INSTALL SONAME 'sql_errlog';

-- Или в my.cnf
[mariadb]
plugin_load_add = sql_errlog
sql_error_log_filename = /var/log/mysql/sql_errors.log
sql_error_log_size_limit = 100M
sql_error_log_rotations = 10
sql_error_log_warnings = ON  -- MariaDB 10.11.5+
```

Проверка установки:

```sql
SELECT PLUGIN_NAME, PLUGIN_STATUS
FROM information_schema.PLUGINS
WHERE PLUGIN_NAME = 'sql_errlog';
```

### 8. Slow query log в таблицу + очистка

Для табличного вывода general/slow query log `TRUNCATE TABLE` очищает данные:

```sql
-- Включить табличный вывод
SET GLOBAL log_output = 'TABLE';
SET GLOBAL slow_query_log = 1;

-- Просмотр
SELECT * FROM mysql.slow_log
ORDER BY start_time DESC LIMIT 10;

-- Очистка (освобождает место)
TRUNCATE TABLE mysql.slow_log;
```

### 9. Поиск пути к error log

```bash
# Через mariadbd
mariadbd --print-defaults | tr " " "\n" | grep log-error

# Через my_print_defaults (MariaDB 10.11+)
my_print_defaults --mariadbd | grep log-error

# Через SQL (если сервер запущен)
mariadb -e "SHOW VARIABLES LIKE 'log_error';"
```

## Операции и команды

### FLUSH — закрытие и переоткрытие логов

```sql
-- Переоткрыть все логи
FLUSH LOGS;

-- Только error log
FLUSH ERROR LOGS;

-- Только slow/general log
FLUSH SLOW LOGS;
FLUSH GENERAL LOGS;

-- Только relay log
FLUSH RELAY LOGS;

-- Только engine log (для MyRocks/InnoDB)
FLUSH ENGINE LOGS;

-- Ротация binlog
FLUSH BINARY LOGS;
```

### SHOW — просмотр статуса логов

```sql
-- Где пишутся логи
SHOW VARIABLES LIKE '%log%';

-- Статус slow query log
SHOW VARIABLES LIKE 'slow_query_log%';
SHOW VARIABLES LIKE 'long_query_time';
SHOW VARIABLES LIKE 'log_output';

-- Список binlog-файлов
SHOW BINARY LOGS;
SHOW MASTER STATUS;

-- GTID позиция
SELECT @@global.gtid_binlog_pos;
```

### PURGE — удаление binlog

```sql
-- По дате
PURGE BINARY LOGS BEFORE '2026-09-27 00:00:00';

-- До файла
PURGE BINARY LOGS TO 'mariadb-bin.000010';

-- Автоочистка (рекомендуется)
SET GLOBAL binlog_expire_logs_seconds = 604800;
```

### TRUNCATE TABLE — очистка табличных логов

```sql
TRUNCATE TABLE mysql.slow_log;
TRUNCATE TABLE mysql.general_log;
```

### Динамическое включение/выключение

```sql
-- Slow query log
SET GLOBAL slow_query_log = 1;          -- вкл
SET GLOBAL slow_query_log = 0;          -- выкл

-- General query log (только для диагностики!)
SET GLOBAL general_log = 1;

-- Отключение на сессии (general log)
SET SESSION sql_log_off = 1;

-- Изменение порога
SET GLOBAL long_query_time = 0.5;

-- Изменение verbosity error log
SET GLOBAL log_warnings = 3;
```

## Особенности и ограничения (Edge Cases)

*   **TABLE log растёт бесконечно:** если `log_output=TABLE`, таблицы `mysql.slow_log` и `mysql.general_log` растут без ограничения. Настраивайте периодический `TRUNCATE TABLE` через cron.
*   **`log_output` нельзя менять в `log_disabled_statements`:** эта переменная только что может быть установлена в `my.cnf`, а не динамически.
*   **`FLUSH LOGS` требует привилегию `RELOAD`:** пользователю в `postrotate` нужна эта привилегия (или `SUPER` в старых версиях).
*   **`logrotate` + `compress` + открытый файл:** если `delaycompress` не задействован, logrotate может заархивировать файл, пока сервер пишет в него — используйте `delaycompress` или `copytruncate`.
*   **SELinux/AppArmor:** при смене пути логов (`/var/log/mysql` → `/data/logs`) необходимо обновить SELinux контекст и/или профиль AppArmor (`/etc/apparmor.d/usr.sbin.mysqld`).
*   **`log_warnings=0`:** не отключает все предупреждения — core warnings всегда пишутся в error log.
*   **Binary log в datadir:** если binlog не вынесен на отдельный диск, `PURGE` не освобождает место на диске из-за файловой системы (особенно ZFS с `recordsize`).
*   **Общий лог и `INSERT` большими батчами:** general query log сериализует все запросы — при высокой нагрузке создает узкое место на запись.
*   **Мульти-инстанс (systemd):** для нескольких экземпляров MariaDB на одном хосте (`mariadb@.service`) используйте разные `--log-error` и `log-basename` на каждом экземпляре.

## Устранение неполадок (Troubleshooting)

### Лог не ротируется

*   **Причина:** logrotate не запущен (cron/timer), неверный путь, файл не существует (`missingok`), права.
*   **Диагностика:** `logrotate -d /etc/logrotate.d/mariadb` (debug-режим); `ls -la /var/log/mysql/`.
*   **Решение:** проверьте пути и права; убедитесь, что `logrotate.timer` или `cron` активен.

### После ротации MariaDB пишет в старый файл

*   **Причина:** сервер держит файл открытым; `FLUSH LOGS` не выполнен.
*   **Диагностика:** `ls -la /var/log/mysql/` — старый файл растёт, новый пуст.
*   **Решение:** используйте `postrotate` с `mariadb-admin flush-logs` или `flush-error-log flush-slow-log`, либо `copytruncate`.

### Диск заполнен binlog

*   **Причина:** `binlog_expire_logs_seconds` не задан или реплики отстали.
*   **Диагностика:** `SHOW BINARY LOGS;` — количество файлов; `du -sh /var/log/mysql/`.
*   **Решение:** установите `binlog_expire_logs_seconds`; проверьте лаг репликации; `PURGE BINARY LOGS BEFORE` (только если реплики прочитали).

### Error log не найден или не пишется

*   **Причина:** `log_error` не задан (лог идёт в `stderr`), путь недоступен для записи, SELinux/AppArmor блокирует.
*   **Диагностика:** `mariadbd --print-defaults | grep log-error`; `SHOW VARIABLES LIKE 'log_error';`; `ls -laZ /var/log/mysql/`.
*   **Решение:** задайте `log_error` в `my.cnf` абсолютным путём; проверьте права (`mysql:mysql`, `0640`); если используется journald — `journalctl -u mariadb`.

### Slow/general log в таблице растёт бесконечно

*   **Причина:** `log_output=TABLE` — `mysql.slow_log` и `mysql.general_log` не очищаются автоматически.
*   **Диагностика:** `SELECT COUNT(*) FROM mysql.slow_log;` — растёт.
*   **Решение:** настройте cron с `TRUNCATE TABLE mysql.slow_log;` и `TRUNCATE TABLE mysql.general_log;`.

### logrotate ругается на права или владельца

*   **Причина:** каталог `/var/log/mysql/` принадлежит `mysql`, но logrotate запущен от `root` с неверным `su`.
*   **Диагностика:** `logrotate -d /etc/logrotate.d/mariadb` — ошибка `error: skipping ... because parent directory has insecure permissions`.
*   **Решение:** добавьте `su mysql mysql` в блок конфигурации logrotate.

## Лучшие практики (Best Practices)

1.  **Binlog — только через `PURGE`/`binlog_expire_logs_seconds`**, никогда через logrotate.
2.  **`postrotate` + `FLUSH LOGS`** для error/slow/general logs — надёжнее `copytruncate`.
3.  **Сжимайте ротированные логи** (`compress`, `delaycompress`).
4.  **Ограничьте количество копий** (`rotate 30` для daily или `maxsize 100M`).
5.  **Мониторьте место** на `/var/log/mysql/` и `tmpdir`.
6.  **General log — только для диагностики** (выключайте после использования).
7.  **Очищайте чувствительные данные:** если general/slow log включался для расследований — удаляйте лог через `shred -u`, а не просто `rm`.
8.  **Настраивайте `log_warnings = 2` на production**, `= 3` — только для короткой отладки (InnoDB DDL progress сильно увеличивает объём лога).

### Очистка и откат

*   Отключить general log: `SET GLOBAL general_log = 0;` или закомментировать в `my.cnf`.
*   Очистить табличный general log: `TRUNCATE TABLE mysql.general_log;`.
*   Проверить, что logrotate активен: `systemctl status logrotate.timer` или `systemctl list-timers | grep logrotate`.
*   Удалить `logrotate`-конфиг: `rm /etc/logrotate.d/mariadb` (только если ротация больше не нужна).

## Дополнительная информация

### См. также

*   **[logrotate (Linux)](../../Linux/SystemAdministration/Logging/logrotate.md)** — общая теория и конфигурация logrotate.
*   **[Бинарное логирование](security/binary-logging.md)** — архитектура binlog, GTID, шифрование.
*   **[Резервное копирование и PITR](backup_and_recovery.md)** — использование binlog для PITR.
*   **[Репликация: relay log](replication/relay_log_management.md)** — управление relay log.
*   **[Мониторинг](monitoring.md)** — slow query log и анализ через `mariadb-dumpslow`.
*   **[Обзор MariaDB](overview.md)** — матрица функций логирования.
*   **[Аудит (security)](security/audit.md)** — server_audit plugin (альтернатива general log).

### Внешние ресурсы

*   [MariaDB Error Log](https://mariadb.com/docs/server/server-management/server-monitoring-logs/error-log.md)
*   [MariaDB Slow Query Log](https://mariadb.com/docs/server/server-management/server-monitoring-logs/slow-query-log/slow-query-log-overview.md)
*   [MariaDB General Query Log](https://mariadb.com/docs/server/server-management/server-monitoring-logs/general-query-log.md)
*   [MariaDB SQL Error Log Plugin](https://mariadb.com/docs/server/server-management/server-monitoring-logs/sql-error-log-plugin.md)
*   [MariaDB Binary Log](https://mariadb.com/docs/server/server-management/server-monitoring-logs/binary-log.md)
*   [MariaDB FLUSH](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/flush-commands/flush.md)
*   [logrotate man page](https://man7.org/linux/man-pages/man8/logrotate.8.html)