# Справочник кодов ошибок MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Error Code** — числовой код ошибки, возвращаемый MariaDB Server (например, `1045`). Коды сервера находятся в диапазоне 1000–4999; коды клиента (клиентская библиотека) — 2000–2999.
*   **SQLSTATE** — пятизначный код состояния по стандарту SQL (например, `28000`), группирующий ошибки по классам. Первые два символа — класс: `00` — успех, `01` — warning, `02` — not found, `08` — connection exception, `22` — data exception, `23` — constraint violation, `28` — authorization/authentication, `42` — syntax/access rule.
*   **Symbolic Name** — символьное имя ошибки в исходном коде (например, `ER_ACCESS_DENIED_ERROR`). Используется в логах и при поиске в документации.
*   **`SHOW ERRORS` / `SHOW WARNINGS`** — операторы, возвращающие ошибки и предупреждения последнего оператора в текущей сессии.
*   **`perror`** — утилита, интерпретирующая коды ошибок ОС (например, `perror 115` → `Operation now in progress`). Полезна для диагностики клиентских ошибок 2002/2003.

## Базовые концепции

### Структура сообщения об ошибке

```
ERROR <code> (<sqlstate>): <message>
```

Пример:
```
ERROR 1045 (28000): Access denied for user 'root'@'localhost' (using password: YES)
```

*   `1045` — код ошибки сервера.
*   `28000` — SQLSTATE (класс авторизации/аутентификации).
*   Текст — человекочитаемое описание.

### Классы SQLSTATE

| SQLSTATE | Класс | Значение |
| :--- | :--- | :--- |
| `00xxx` | Успех | Операция завершена успешно |
| `01xxx` | Warning | Предупреждение (операция выполнена) |
| `02xxx` | Not found | Данные не найдены (курсоры) |
| `08xxx` | Connection exception | Ошибки соединения |
| `22xxx` | Data exception | Ошибки данных (деление на ноль, переполнение) |
| `23xxx` | Constraint violation | Нарушение ограничений (FK, unique) |
| `28xxx` | Authorization/authentication | Ошибки аутентификации |
| `42xxx` | Syntax rule / access rule | Синтаксические ошибки, несуществующие объекты |

## Справочник частых кодов ошибок

### Ошибки соединения и аутентификации

| Код | SQLSTATE | Символьное имя | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- | :--- |
| **1040** | `08004` | `ER_CON_COUNT_ERROR` | Too many connections | Исчерпан `max_connections`. Увеличьте `max_connections`, включите Thread Pool, настройте connection pooling (ProxySQL/MaxScale). Проверьте `SHOW STATUS LIKE 'Threads_connected'`. |
| **1044** | `42000` | `ER_DBACCESS_DENIED_ERROR` | Access denied for user to database | Нет прав на БД. `GRANT` нужных привилегий на конкретную БД. |
| **1045** | `28000` | `ER_ACCESS_DENIED_ERROR` | Access denied for user (using password) | Неверный логин/пароль или нет прав. Проверьте `mysql.user`, хост пользователя, плагин аутентификации. Для root на localhost — `sudo mariadb` (unix_socket). |
| **1227** | `42000` | `ER_SPECIFIC_ACCESS_DENIED_ERROR` | Access denied; you need privilege for this operation | Не хватает конкретной привилегии (например, `REPLICATION SLAVE`, `SUPER`). |
| **1396** | `HY000` | `ER_CANNOT_USER` | Operation CREATE USER/DROP USER failed | Пользователь уже существует (или не существует при DROP). Проверьте `mysql.user`. |
| **2002** | `HY000` | `CR_CONNECTION_ERROR` | Can't connect to local MySQL server through socket | Сервер не запущен или socket в другом пути. `systemctl status mariadb`; проверьте `socket` в `my.cnf`. |
| **2003** | `HY000` | `CR_CONN_HOST_ERROR` | Can't connect to MySQL server on 'host' | Сервер недоступен по TCP: не запущен, firewall, неверный порт/хост. `telnet host 3306`; `perror 111` (Connection refused). |
| **2006** | `HY000` | `CR_SERVER_GONE_ERROR` | MySQL server has gone away | Соединение разорвано: таймаут (`wait_timeout`), `max_allowed_packet` превышен, сервер перезапущен. Увеличьте `wait_timeout`, `max_allowed_packet`. |
| **2013** | `HY000` | `CR_SERVER_LOST` | Lost connection to MySQL server during query | Соединение потеряно во время запроса: долгий запрос, таймаут, сетевой сбой. |

### Ошибки данных и ограничений

| Код | SQLSTATE | Символьное имя | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- | :--- |
| **1007** | `HY000` | `ER_DB_CREATE_EXISTS` | Can't create database; database exists | БД уже существует. Используйте `CREATE DATABASE IF NOT EXISTS`. |
| **1008** | `HY000` | `ER_DB_DROP_EXISTS` | Can't drop database; database doesn't exist | БД не существует. |
| **1022** | `23000` | `ER_DUP_KEY` | Can't write; duplicate key in table | Дубликат ключа при записи. Проверьте уникальные индексы. |
| **1049** | `42000` | `ER_BAD_DB_ERROR` | Unknown database | БД не существует. Проверьте имя БД. |
| **1050** | `42S01` | `ER_TABLE_EXISTS_ERROR` | Table already exists | Таблица существует. `CREATE TABLE IF NOT EXISTS`. |
| **1051** | `42S02` | `ER_BAD_TABLE_ERROR` | Unknown table | Таблица не существует. |
| **1054** | `42S22` | `ER_BAD_FIELD_ERROR` | Unknown column | Столбец не существует. Проверьте имя столбца. |
| **1062** | `23000` | `ER_DUP_ENTRY` | Duplicate entry for key | Дубликат уникального/первичного ключа. Самая частая ошибка INSERT. Решение: `INSERT IGNORE`, `ON DUPLICATE KEY UPDATE`, или проверка перед вставкой. |
| **1064** | `42000` | `ER_PARSE_ERROR` | You have an error in your SQL syntax | Синтаксическая ошибка SQL. Проверьте синтаксис, зарезервированные слова. |
| **1146** | `42S02` | `ER_NO_SUCH_TABLE` | Table doesn't exist | Таблица не существует (в контексте запроса). |
| **1216** | `23000` | `ER_NO_REFERENCED_ROW` | Cannot add or update a child row | Нарушение FK: родительская строка не найдена. |
| **1217** | `23000` | `ER_ROW_IS_REFERENCED` | Cannot delete or update a parent row | Нарушение FK: есть дочерние строки. |
| **1451** | `23000` | `ER_ROW_IS_REFERENCED_2` | Cannot delete or update a parent row (FK) | Аналог 1217, расширенное сообщение. |
| **1452** | `23000` | `ER_NO_REFERENCED_ROW_2` | Cannot add or update a child row (FK) | Аналог 1216, расширенное сообщение. |

### Ошибки блокировок и транзакций

| Код | SQLSTATE | Символьное имя | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- | :--- |
| **1205** | `HY000` | `ER_LOCK_WAIT_TIMEOUT` | Lock wait timeout exceeded | Транзакция ждала блокировку дольше `innodb_lock_wait_timeout` (по умолчанию 50с). Сократите транзакции, добавьте индексы, проверьте `sys.innodb_lock_waits`. |
| **1213** | `40001` | `ER_LOCK_DEADLOCK` | Deadlock found when trying to get lock | Deadlock: InnoDB откатил одну из транзакций. Приложение должно повторить транзакцию. Сократите транзакции, упорядочьте доступ к строкам. |
| **1207** | `HY000` | `ER_READ_ONLY_TRANSACTION` | Read only transactions can't be in a recoverable lock | Попытка записи в read-only транзакции. |

### Ошибки репликации

| Код | SQLSTATE | Символьное имя | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- | :--- |
| **1236** | `HY000` | `ER_MASTER_INFO` / binlog errors | Could not find first log file name in binary log index | Relay log или binlog повреждены/удалены. Проверьте `SHOW REPLICA STATUS`, `Last_IO_Error`. |
| **1594** | `HY000` | `ER_RELAY_LOG_CORRUPT` | Relay log read failure | Relay log повреждён. `relay_log_recovery = ON` для автоматического восстановления. |
| **1846** | `HY000` | `ER_SLAVE_CONFIGURATION` | ERROR_REPLICATION | Ошибка конфигурации репликации (неверный `CHANGE REPLICATION SOURCE TO`). |

### Ошибки DDL и обслуживания

| Код | SQLSTATE | Символьное имя | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- | :--- |
| **1005** | `HY000` | `ER_CANT_CREATE_TABLE` | Can't create table | Ошибка создания таблицы: часто нарушение FK (проверьте `SHOW ENGINE INNODB STATUS`). |
| **1016** | `HY000` | `ER_CANT_OPEN_FILE` | Can't open file | Файл таблицы не открывается: повреждение .ibd, нехватка места, права. |
| **1032** | `HY000` | `ER_KEY_NOT_FOUND` | Can't find record in 'table' | Запись не найдена при операции, требующей существования (часто в репликации). |
| **1114** | `HY000` | `ER_RECORD_FILE_FULL` | The table is full | Таблица заполнилась: достигнут лимит диска или `max_rows`. |
| **1820** | `HY000` | `ER_PASSWORD_EXPIRE` | You must reset your password using ALTER USER statement | Пароль истёк. `ALTER USER ... IDENTIFIED BY ...`. |

## Практические сценарии

### 1. Диагностика ошибки в сессии

```sql
-- Ошибки и предупреждения последнего оператора
SHOW ERRORS;
SHOW WARNINGS;

-- Количество ошибок/предупреждений
SHOW COUNT(*) ERRORS;
SHOW COUNT(*) WARNINGS;

-- Интерпретация кода ОС
-- В shell:
perror 111
# → OS error code 111: Connection refused
```

### 2. Поиск ошибок в логах

```bash
# Ошибки за последний час
journalctl -u mariadb --since "1 hour ago" | grep -i error

# Конкретный код ошибки
journalctl -u mariadb | grep "1045"

# Deadlocks
journalctl -u mariadb | grep -i deadlock
```

### 3. Обработка дубликата ключа (1062) в приложении

```sql
-- Игнорировать дубликат
INSERT IGNORE INTO users (email) VALUES ('test@example.com');

-- Обновить при дубликате
INSERT INTO users (email, name) VALUES ('test@example.com', 'Test')
  ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Проверить существование перед вставкой
SELECT id FROM users WHERE email = 'test@example.com';
```

### 4. Диагностика deadlock (1213)

```sql
-- Последний deadlock
SHOW ENGINE INNODB STATUS\G
-- Секция "LATEST DETECTED DEADLOCK"

-- Текущие ожидания блокировок
SELECT * FROM sys.innodb_lock_waits;

-- Транзакции InnoDB
SELECT * FROM information_schema.INNODB_TRX;
```

## Устранение неполадок (Troubleshooting)

### Too many connections (1040)

*   **Диагностика:** `SHOW STATUS LIKE 'Threads_connected';` vs `SHOW VARIABLES LIKE 'max_connections';`. `SHOW PROCESSLIST` — кто держит соединения.
*   **Решение:** увеличьте `max_connections`; включите Thread Pool; настройте connection pooling на стороне приложения (ProxySQL/MaxScale); сократите `wait_timeout` для закрытия idle-соединений.

### Access denied (1045)

*   **Диагностика:** `SELECT User, Host, plugin FROM mysql.user WHERE User = '...';` — проверьте хост и плагин. Для root на localhost — `sudo mariadb` (unix_socket).
*   **Решение:** создайте пользователя с нужным хостом; сбросьте пароль через `mysql_upgrade`/`skip-grant-tables` (только для восстановления).

### Server has gone away (2006)

*   **Диагностика:** проверьте `wait_timeout`, `max_allowed_packet`, размер запроса.
*   **Решение:** увеличьте `wait_timeout` (по умолчанию 28800с = 8ч) и `max_allowed_packet` (по умолчанию 16M); разбейте большие запросы.

## Лучшие практики (Best Practices)

1.  **Читайте SQLSTATE:** класс ошибки (`23xxx` — ограничения, `08xxx` — соединение) быстрее указывает на категорию проблемы, чем текст.
2.  **Обрабатывайте 1062 и 1213 в приложении:** дубликат ключа и deadlock — нормальные операционные ситуации; приложение должно их обрабатывать (retry).
3.  **Используйте `SHOW ERRORS`** после неудачного оператора для получения деталей.
4.  **`perror` для клиентских ошибок** (2002/2003) — интерпретирует коды ОС.
5.  **Мониторьте частоту ошибок** через `SHOW GLOBAL STATUS LIKE 'Aborted_%'` и алерты Prometheus.

## Дополнительная информация

### См. также

*   **[Устранение неполадок: runbook](troubleshooting_runbook.md)** — единый runbook диагностики.
*   **[Репликация: troubleshooting](replication/troubleshooting.md)** — ошибки репликации.
*   **[Транзакции и блокировки](transactions_and_locking.md)** — deadlocks, lock waits.
*   **[Мониторинг](monitoring.md)** — алерты на ошибки.

### Внешние ресурсы

*   [MariaDB Error Codes](https://mariadb.com/docs/server/reference/error-codes/)
*   [MariaDB Error Codes 1000–1099](https://mariadb.com/docs/server/reference/error-codes/mariadb-error-codes-1000-to-1099/)
*   [MariaDB Error Codes 1200–1299](https://mariadb.com/docs/server/reference/error-codes/mariadb-error-codes-1200-to-1299/)
*   [MariaDB Error Code Reference](https://mariadb.com/docs/server/reference/error-code-reference/)
*   [MariaDB Troubleshooting Connection Issues](https://mariadb.com/docs/server/quickstart-guides/mariadb-connection-troubleshooting-guide/)
