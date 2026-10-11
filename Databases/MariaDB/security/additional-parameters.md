# Дополнительные параметры безопасности MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

Параметры `my.cnf`, которые закрывают конкретные классы атак и не покрываются сетевым контролем или аутентификацией. Они формируют второй слой защиты поверх файрвола и ролевой модели.

## Определения

- **local-infile** — разрешает или запрещает клиентам выполнять `LOAD DATA LOCAL INFILE` и `LOAD XML`. При `OFF` сервер игнорирует запросы на локальную загрузку файлов, исключая чтение `/etc/passwd`, `/etc/shadow` и других файлов ОС через SQL-инъекцию.
- **skip-show-database** — скрывает список всех баз данных от пользователей без привилегии `SHOW DATABASES`. Без этого параметра любой аккаунт, способный подключиться, видит имена всех БД в инстансе.
- **symbolic-links** — разрешает или запрещает символические ссылки в `datadir`. При `OFF`MariaDB игнорирует symlink-записи в `.frm`/`.ibd`, исключая атаки через path traversal и перезапись файлов через симлинки.
- **secure-file-priv** — каталог, в который разрешены `LOAD DATA INFILE`, `SELECT ... INTO OUTFILE` и `LOAD XML`. Если параметр пуст — эти команды работают везде, что расширяет поверхность атаки.
- **require_secure_transport** — требует шифрования TLS для всех TCP-подключений. Без него даже настроенный SSL/TLS может быть обойдён клиентом, который подключается без шифрования.
- **log_warnings** — уровень детализации error log (0–9). `0` — минимум; `2` (по умолчанию) — ошибки, предупреждения, access denied; `3` — + InnoDB DDL progress; `4` — + killed connections; `9` — + инициализация плагинов. MariaDB не поддерживает MySQL-переменную `log_error_verbosity`.
- **connect_timeout** — время ожидания приёма ответа на пакет рукопожатия (в секундах). Защищает от медленных SYN/ACK-атак и зависающих неавторизованных соединений в очереди.
- **max_statement_time** — максимальное время выполнения одного оператора (в секундах). `0` — без ограничения. Защищает от DoS через `SLEEP()`, `BENCHMARK()` или ненастроенные `JOIN`.
- **sql_mode** — набор режимов, изменяющих поведение парсера и проверку данных. Определяет обработку неверных дат, деления на ноль, отсутствующих значений и подстановки движков. Подробный разбор флагов, дефолтов и расширения профиля — в **[SQL_MODE в MariaDB](../sql_mode.md)**.
- **read_only** — включает режим «только чтение» для всех не-SUPER аккаунтов. Используется на репликах и при техническом обслуживании.
- **super_read_only** — расширяет `read_only`, блокируя запись даже для аккаунтов с привилегией `SUPER`. Добавлен в MariaDB 10.5.1. Требует предварительного включения `read_only = ON`.
- **userstat** — включает сбор статистики по пользователям и таблицам. При `ON` любной аккаунт с доступом к `information_schema.USER_STATISTICS` видит активность других пользователей.

## Архитектура и базовые принципы

Безопасность MariaDB строится по модели разделения плоскостей:

1. **Сетевая плоскость** — ограничивает, кто может подключиться. Параметры: `bind-address`, `skip-networking`, файрвол. Подробнее: **[Сетевая безопасность](network-security.md)**.
2. **Аутентификационная плоскость** — определяет, как сервер проверяет личность. Параметры: `unix_socket`, `caching_sha2_password`, `ed25519`, `default_password_lifetime`. Подробнее: **[Аутентификация](authentication.md)**.
3. **Авторизационная плоскость** — определяет, что пользователь может делать. Параметры: `skip-show-database`, `sql_mode`, роли. Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.
4. **Плоскость данных и экспорта** — контролирует, как данные покидают сервер. Параметры: `local-infile`, `secure-file-priv`, `symbolic-links`.
5. **Плоскость транспорта** — контролирует, как данные передаются по сети. Параметры: `require_secure_transport`, TLS-настройки. Подробнее: **[SSL/TLS](ssl-tls.md)**.
6. **Плоскость аудита** — фиксирует, что происходит. Параметры: `log_warnings`, `server_audit` плагин. Подробнее: **[Аудит](audit.md)**.

Дополнительные параметры закрывают пробелы между этими плоскостями. Например, `require_secure_transport` связывает сетевую плоскость с плоскостью транспорта; `secure-file-priv` связывает плоскость данных с авторизационной.

## Практические сценарии

### Защита от экспорта файлов и локальной загрузки

```ini
[mariadb]
# Запрет загрузки файлов через SQL (LOAD DATA INFILE / LOAD XML)
local-infile = 0

# Ограничение директории для экспорта/импорта (защита от чтения /etc/passwd)
# Путь должен существовать и иметь владельца mysql:mysql
secure-file-priv = /var/lib/mysql-files
```

```sql
-- Проверка текущего значения secure-file-priv
SHOW VARIABLES LIKE 'secure_file_priv';
-- → /var/lib/mysql-files

-- Проверка, что local-infile отключён
SHOW VARIABLES LIKE 'local_infile';
-- → OFF
```

### Скрытие метаданных и снижение информационного раскрытия

```ini
[mariadb]
# Скрытие списка БД от непривилегированных пользователей
skip-show-database = 1

# Минимальная детализация error log (0-9, 2=по умолчанию)
log_warnings = 2

# Отключение символических ссылок (защита от Path Traversal)
symbolic-links = 0
```

### Ограничение времени выполнения и защита от DoS

```ini
[mariadb]
# Таймаут аутентификации (защита от медленных brute-force)
connect_timeout = 10

# Таймаут неактивных соединений (секунды)
wait_timeout = 600
interactive_timeout = 600

# Максимальное время одного оператора (защита от SLEEP()/BENCHMARK)
max_statement_time = 30

# Лимит одновременных соединений на пользователя
max_user_connections = 50
```

```sql
-- Проверка текущих таймаутов
SHOW VARIABLES LIKE 'connect_timeout';
SHOW VARIABLES LIKE 'wait_timeout';
SHOW VARIABLES LIKE 'max_statement_time';
SHOW VARIABLES LIKE 'max_user_connections';
```

### Принудительное шифрование транспорта

```ini
[mariadb]
# Требовать TLS для всех TCP-подключений
require_secure_transport = ON
```

```sql
-- Проверка текущего состояния
SHOW VARIABLES LIKE 'require_secure_transport';
-- → ON
```

> **Важно:** `require_secure_transport` блокирует подключения без TLS. Убедитесь, что все клиенты и приложения настроены на шифрование перед включением. Подробнее о настройке TLS: **[SSL/TLS](ssl-tls.md)**.

### Режим «только чтение» для реплик и обслуживания

```ini
[mariadb]
# Режим только чтение (для реплик или обслуживания)
read_only = ON

# Супер-режим только чтение (блокирует даже SUPER-аккаунты)
# Включите только после read_only = ON
super_read_only = ON
```

```sql
-- Проверка режима
SHOW VARIABLES LIKE 'read_only';
SHOW VARIABLES LIKE 'super_read_only';

-- Временная разблокировка для обслуживания (только для SUPER)
SET GLOBAL super_read_only = OFF;
-- ...выполните обслуживание...
SET GLOBAL super_read_only = ON;
```

> **Важно:** `super_read_only` добавлен в MariaDB 10.5.1. На версиях до 10.5 используйте только `read_only = ON`.

### Отключение сбора пользовательской статистики

```ini
[mariadb]
userstat = 0
```

```sql
-- Проверка
SHOW VARIABLES LIKE 'userstat';
-- → OFF
```

## Валидация

```bash
# Проверка, что local-infile отключён
mysql -u root -e "SHOW VARIABLES LIKE 'local_infile';"
# → local_infile = OFF

# Проверка secure-file-priv
mysql -u root -e "SHOW VARIABLES LIKE 'secure_file_priv';"
# → /var/lib/mysql-files

# Проверка skip-show-database
mysql -u root -e "SHOW VARIABLES LIKE 'skip_show_database';"
# → skip_show_database = ON

# Проверка require_secure_transport
mysql -u root -e "SHOW VARIABLES LIKE 'require_secure_transport';"
# → ON

# Проверка symbolic-links
mysql -u root -e "SHOW VARIABLES LIKE 'have_symlink';"
# → DISABLED

# Проверка log_warnings
mysql -u root -e "SHOW VARIABLES LIKE 'log_warnings';"
# → 2

# Проверка sql_mode (подробнее в ../sql_mode.md)
mysql -u root -e "SELECT @@sql_mode;"
# → STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,...

# Проверка read_only / super_read_only
mysql -u root -e "SHOW VARIABLES LIKE 'read%';"
# → read_only = ON, super_read_only = ON

# Проверка userstat
mysql -u root -e "SHOW VARIABLES LIKE 'userstat';"
# → OFF
```

## Устранение неполадок

### Ошибка: приложение не может экспортировать CSV через `SELECT ... INTO OUTFILE`

**Симптом:** `The MySQL server is running with the --secure-file-priv option so it cannot execute this statement`

**Причина:** `secure-file-priv` настроен на каталог, отличный от того, куда приложение пытается записать файл.

**Решение:**
1. Проверьте значение: `SHOW VARIABLES LIKE 'secure_file_priv';`
2. Переместите файл в разрешённый каталог или измените параметр в `my.cnf` и перезапустите MariaDB.
3. Убедитесь, что каталог существует и имеет владельца `mysql:mysql` (`chmod 755`).

### Ошибка: `skip-show-database` блокирует приложение

**Симптом:** Приложение получает `Access denied; you need the SHOW DATABASES privilege for this operation`

**Причина:** Приложение запрашивает список баз данных через `SHOW DATABASES` или `information_schema.SCHEMATA` без явной привилегии.

**Решение:**
1. Если приложение должно видеть только определённые БД — создайте отдельного пользователя с правами только на эти БД.
2. Если приложение требует полный список — выдача `SHOW DATABASES` снижает безопасность. Рассмотрите изменение архитектуры приложения.

### Ошибка: `require_secure_transport` блокирует старые клиенты

**Симптом:** `ERROR 2026 (HY000): SSL connection error: Unable to get certificate`

**Причина:** Клиент не поддерживает TLS или использует устаревший протокол/шифр.

**Решение:**
1. Проверьте поддерживаемые шифры клиентом: `mysql --ssl-mode=REQUIRED -e "SELECT 1"`
2. На сервере проверьте `SHOW VARIABLES LIKE 'have_ssl';` и `SHOW VARIABLES LIKE 'tls_version';`
3. Если не удаётся обновить клиент — временно установите `require_secure_transport = DISABLED` для миграции, но верните `ON` после обновления.

### Ошибка: `super_read_only` не применяется

**Симптом:** `SHOW VARIABLES LIKE 'super_read_only'` показывает `OFF`, хотя в `my.cnf` указано `ON`.

**Причина:** `super_read_only` не может быть включён, если `read_only = OFF`. MariaDB игнорирует `super_read_only` при отсутствии базового `read_only`.

**Решение:**
1. Включите `read_only = ON` первым: `SET GLOBAL read_only = ON;`
2. Затем включите `super_read_only = ON`: `SET GLOBAL super_read_only = ON;`
3. Зафиксируйте в `my.cnf` и перезапустите.

## Рекомендации

- Включайте `local-infile = 0` и `secure-file-priv` на всех production-инстансах, кроме тех, где импорт данных через `LOAD DATA` является постоянной операцией. В последнем случае настройте `secure-file-priv` на выделенный каталог и ограничьте его права (`mysql:mysql`, `0750`).
- Используйте `skip-show-database = 1` совместно с ролевой моделью: создайте отдельных пользователей для приложений с правами только на необходимые БД.
- Включайте `require_secure_transport = ON` сразу после настройки TLS. Проверяйте через `SHOW STATUS LIKE 'Ssl_cipher';` — если статус пустой, соединение не шифруется.
- На репликах используйте `read_only = ON` для предотвращения случайных записей. `super_read_only = ON` добавляйте только для обслуживания, когда даже админ не должен случайно записать данные.
- Не оставляйте `max_statement_time = 0` на production-инстансах с публичным доступом. Установите разумный лимит (например, `30-60` секунд) и мониторьте долгие запросы через `slow_query_log`.
- Настройте `log_warnings = 2` для production. Уровень `3` полезен только при расследовании инцидентов, но создаёт большой объём логов из-за InnoDB DDL progress.
- Настройте `sql_mode` в `my.cnf` и обновляйте вручную после каждого `mariadb-upgrade` (подробнее в **[SQL_MODE в MariaDB](../sql_mode.md)**).
- Регулярно аудитируйте `SHOW GRANTS` для аккаунтов с `SUPER` или `FILE` привилегиями. Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.

## См. также

- **[Обзор безопасности](index.md)** — общая многоуровневая модель безопасности.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и OS-level hardening.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, `max_connections`, `wait_timeout`, файрвол.
- **[SSL/TLS](ssl-tls.md)** — шифрование трафика, `require_secure_transport`, mTLS.
- **[Аутентификация](authentication.md)** — плагины, `caching_sha2_password`, brute-force защита.
- **[Ролевая модель (RBAC)](rbac.md)** — `REVOKE`, роли, `SHOW GRANTS`.
- **[Аудит](audit.md)** — `server_audit` плагин, комплаенс, SIEM.
- **[Шифрование данных (TDE)](tde.md)** — `binlog_encryption`, `innodb_encrypt_tables`.
- **[Конфигурация MariaDB](../configuration.md)** — полный список параметров `my.cnf`, приоритеты загрузки.

## Дополнительная информация

- [MariaDB Server System Variables](https://mariadb.com/docs/server/server-system-variables/)
- [MariaDB SQL Mode](https://mariadb.com/docs/server/sql-mode/)
- [MariaDB Read Only Variables](https://mariadb.com/docs/server/sql-statements/storage-engines/replication-statistics/#read-only-and-super-read-only)
- [CIS MariaDB Benchmark](https://www.cisecurity.org/benchmark/mariadb)
