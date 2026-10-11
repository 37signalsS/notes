# Управление ролями и правами доступа в PostgreSQL (RBAC)

**Актуально для:** PostgreSQL 13–18

## Определения

- **Роль (Role)** — именованная сущность **на уровне кластера**: определена один раз и действует во всех базах данных кластера. Может владеть объектами и получать привилегии.
- **Пользователь (User)** — роль с атрибутом `LOGIN`, позволяющим подключаться к БД. `CREATE USER` = `CREATE ROLE` с `LOGIN` по умолчанию.
- **Групповая роль (Group Role)** — роль без `LOGIN` (по умолчанию `NOLOGIN`), объединяющая привилегии для наследования пользователями.
- **Владелец (Owner)** — роль, создавшая объект (таблицу, схему, базу) или получившая владение через `ALTER ... OWNER TO`.
- **Предопределённые роли (Predefined Roles)** — системные роли для делегирования типовых прав без выдачи `SUPERUSER` (ранее — «default roles», термин изменён в PG 14).
- **Членство (Membership)** — включение роли в другую роль; привилегии членства управляются опциями `INHERIT`, `SET`, `ADMIN` (PG 16+).
- **Привилегия (Privilege)** — право на конкретный тип операции над конкретным объектом (`SELECT`, `USAGE`, `EXECUTE` и др.); выдаётся `GRANT` и не наследуется автоматически — наследуются только выданные привилегии и членства.

По умолчанию при инициализации кластера создаётся роль `postgres` (суперпользователь, bootstrap).

## Предпосылки

1. **Права:** суперпользователь (`postgres`) или роль с атрибутом `CREATEROLE` для создания ролей. Суперпользователь нужен для смены паролей других ролей и управления предопределёнными ролями произвольно.
2. **Аутентификация:** корректно настроенный `pg_hba.conf` — без подходящей записи даже созданная роль не подключится. Методы и формат файла — в **[Безопасности и шифровании](../Concepts/security_and_encryption.md)**.
3. **Версии СУБД** (что доступно в какой ветке):
   - **PG 14+:** `pg_read_all_data`, `pg_write_all_data`, `pg_database_owner`.
   - **PG 15+:** `pg_read_server_files`, `pg_write_server_files`, `pg_execute_server_program`; у роли `PUBLIC` отозвано право `CREATE` на схему `public`.
   - **PG 16+:** опции членства `WITH {ADMIN | INHERIT | SET}` в `GRANT`; ограничены привилегии `CREATEROLE`.
   - **PG 17+:** `pg_maintain`, `pg_checkpoint`, `pg_use_reserved_connections`.
   - **PG 18+:** `pg_create_subscription`.
4. **Клиент:** `psql` (метаправила `\du`, `\dp`, `\password`) — см. **[Основы работы в psql](./console_basics.md)**.

## Основные концепции

### Роли, пользователи и группы

Роль — единый механизм для пользователей, групп и владельцев. Разница только в атрибутах:

```sql
-- Проверка атрибутов роли
SELECT rolname, rolcanlogin, rolinherit, rolsuper
FROM pg_roles WHERE rolname = 'app_user';
-- → rolname  | rolcanlogin | rolinherit | rolsuper
-- → app_user | t           | t          | f
```

**Атрибуты роли не наследуются через членство:** вход в роль с `CREATEDB` не даёт члену право создавать базы — для этого нужен `SET ROLE` (или опция `SET TRUE` на членстве). Наследуются только объектные привилегии и членства.

### Атрибуты роли

| Атрибут | Суть |
| :--- | :--- |
| `LOGIN` / `NOLOGIN` | Роль пригодна как имя для подключения (`CREATE USER` подразумевает `LOGIN`) |
| `SUPERUSER` | Обходит все проверки прав (кроме права на вход) — только для администрирования |
| `CREATEDB` / `CREATEROLE` | Создание баз / ролей |
| `REPLICATION` | Инициация streaming-репликации (требуется также `LOGIN`) |
| `BYPASSRLS` | Обход всех политик RLS (суперпользователи обходят RLS всегда) |
| `INHERIT` / `NOINHERIT` | Наследовать привилегии ролей-членов по умолчанию (`INHERIT` — дефолт) |
| `CONNECTION LIMIT n` | Лимит одновременных подключений роли; `-1` (дефолт) — без лимита. Считаются только обычные подключения (prepared-транзакции и background-воркеры не считаются) |
| `PASSWORD '...'` | Пароль (полезен только для `LOGIN`-ролей; `NULL` — password-аутентификация всегда неудачна) |
| `VALID UNTIL 'timestamp'` | Срок действия **пароля** (не самой роли!); `timestamp` без часового пояса; не применяется при не-парольных методах аутентификации (`peer`, `cert`); `'infinity'` — бессрочно |

**`CREATEROLE` в PG 16+ ограничен:** роль с `CREATEROLE` может изменять/удалять и управлять членством только тех ролей, которые выданы ей с `ADMIN OPTION` (при создании роли через `CREATEROLE` новая роль автоматически выдаётся создателю с `WITH ADMIN TRUE, SET FALSE, INHERIT FALSE`). `CREATEROLE` **не** даёт: создавать `SUPERUSER`-роли, управлять `REPLICATION`-ролями (кроме `ALTER ... SET`/`RENAME`/`COMMENT`/`DROP`), выдавать/отзывать `BYPASSRLS`.

### Членство и наследование

```sql
-- Членство с управляемыми опциями (PG 16+):
-- ADMIN  — член может сам выдавать/отзывать членство
-- SET    — член может делать SET ROLE к этой роли
-- INHERIT— привилегии роли доступны автоматически (дефолт TRUE)
GRANT read_only_group TO app_user WITH INHERIT TRUE, SET TRUE, ADMIN FALSE;

-- Проверка членств и опций
SELECT member_roleid::regrole AS member, parent_roleid::regrole AS granted_role,
       admin_option, inherit_option, set_option
FROM pg_auth_members;
```

`IN ROLE` / `ROLE` / `ADMIN` в `CREATE ROLE` задают начальное членство (новое членство получает `SET TRUE`, `ADMIN FALSE`, `INHERIT TRUE` если не указано `NOINHERIT`). `SET ROLE` требует цепочки членств с `SET TRUE`; `SET SESSION AUTHORIZATION` меняет идентификатор сессии (детали и тестирование — в **[Безопасности](../Concepts/security_and_encryption.md)**).

### Иерархия привилегий

Привилегии выдаются сверху вниз: `DATABASE` → `SCHEMA` → объекты. Для доступа к объекту нужна `USAGE` на схему, для подключения — `CONNECT` на базу:

| Уровень | Привилегии | Назначение |
| :--- | :--- | :--- |
| `DATABASE` | `CONNECT`, `CREATE`, `TEMP` | Подключение, создание схем, временных таблиц |
| `SCHEMA` | `USAGE`, `CREATE` | Видимость/доступ к объектам схемы; создание объектов в ней |
| `TABLE` | `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` | DML и ссылочная целостность |
| `SEQUENCE` | `USAGE`, `SELECT`, `UPDATE` | **Требуется для `serial`/`identity`-столбцов** — частая причина `permission denied for sequence` |
| `FUNCTION` / `PROCEDURE` | `EXECUTE` | Вызов хранимых объектов (по умолчанию `EXECUTE` выдан `PUBLIC`) |
| `DATABASE` (клиент) | `CREATE SUBSCRIPTION` (PG 18+ через `pg_create_subscription`) | Логические подписки |

**Системные каталоги:** `pg_roles` — все роли (пароль показывается как `NULL`), `pg_authid` — хэши паролей (только суперпользователь), `pg_auth_members` — членства, `information_schema.role_table_grants` — привилегии на таблицы.

## Практические сценарии

### Подключение к консоли управления

```bash
sudo -u postgres psql          # прямой вход (peer-аутентификация)
```

Способы подключения и настройки клиента — в **[Основах работы в psql](./console_basics.md)**.

### Создание ролей через SQL

```sql
-- Сервисная роль приложения: вход, пароль, лимит сессий, срок действия пароля
CREATE USER app_user
WITH PASSWORD 'secure_pass'
  VALID UNTIL '2026-12-31'      -- срок действия пароля (не роли)
  CONNECTION LIMIT 50;

-- Групповая роль без входа (для объединения прав)
CREATE ROLE read_only_group NOLOGIN;

-- Роль с немедленным членством в группе
CREATE USER report_user WITH LOGIN PASSWORD 'pass' IN ROLE read_only_group;

-- Атрибуты уровня кластера (использовать с осторожностью):
-- SUPERUSER | CREATEDB | CREATEROLE | REPLICATION | BYPASSRLS
```

> **Не выдавайте `BYPASSRLS` приложениям** — он обходит все политики RLS. Нужен только для отдельных сервисных ролей (например, дампера с полным доступом).

### Создание через утилиту createuser

Обёртка над `CREATE ROLE`; запускать от суперпользователя или роли с `CREATEROLE`:

```bash
# Создать пользователя с интерактивным вводом пароля
sudo -u postgres createuser app_user -P

# Сразу добавить в группу (аналог IN ROLE)
sudo -u postgres createuser app_user -P -g read_only_group

# Лимит подключений и атрибуты
sudo -u postgres createuser -P -c 50 -d -r app_user

# Интерактивный режим (вопросы о SUPERUSER/CREATEDB/CREATEROLE)
sudo -u postgres createuser --interactive
```

Ключи: `-P, --pwprompt` (пароль **нового** пользователя), `-W, --password` (пароль **для подключения к серверу** — другое!), `-c, --connection-limit`, `-d/-D` (`CREATEDB`), `-r/-R` (`CREATEROLE`), `-s/-S` (`SUPERUSER`), `-l/-L` (`LOGIN`), `-i/-I` (`INHERIT`), `--replication`, `-e, --echo` (эхо генерируемого SQL), `-g, --member-of` (членство; в PG 18 синоним `--role` deprecated).

### Подключение под новой ролью

Способ зависит от метода аутентификации в `pg_hba.conf`:

```bash
# 1. peer-аутентификация (local, дефолт в пакетах Debian/Ubuntu):
#    имя пользователя ОС должно совпадать с именем роли
sudo adduser app_user
sudo -u app_user psql -d mydb

# 2. TCP-аутентификация по паролю (scram-sha-256):
#    пользователь ОС не нужен, пароль запрашивается интерактивно
psql -U app_user -h 127.0.0.1 -d mydb

# 3. Пароль из ~/.pgpass — без запроса (полезно в скриптах и cron)
psql -U app_user -h 127.0.0.1 -d mydb -c "SELECT 1;"
```

Настройка `pg_hba.conf`, `~/.pgpass` и методы аутентификации — в **[Безопасности и шифровании](../Concepts/security_and_encryption.md)** и **[Управлении соединениями](./connection_management.md)**.

### Создание базы данных

По умолчанию роль пытается подключиться к БД с тем же именем; владелец БД получает права через `pg_database_owner`:

```bash
sudo -u postgres createdb mydb                 # владелец — роль, от имени которой запущено
sudo -u postgres createdb -O app_owner mydb    # явный владелец
```

### Предопределённые системные роли

Делегирование прав без `SUPERUSER`. Выдаются суперпользователем (или ролью с `CREATEROLE`):

| Роль | Версия | Право |
| :--- | :--- | :--- |
| `pg_monitor` | 10+ | Читает настройки, статистику и сканирует таблицы (член `pg_read_all_settings`, `pg_read_all_stats`, `pg_stat_scan_tables`) — идеальна для мониторинга |
| `pg_read_all_settings` | 10+ | Чтение всех конфигурационных переменных, включая скрытые |
| `pg_read_all_stats` | 10+ | Чтение всех `pg_stat_*` представлений |
| `pg_stat_scan_tables` | 10+ | Мониторинговые функции, способные брать `ACCESS SHARE`-блокировки |
| `pg_read_all_data` | 14+ | `SELECT` на все таблицы/представления/последовательности + `USAGE` на все схемы. **Не** имеет `BYPASSRLS` — при RLS администратор должен выдать `BYPASSRLS` явно |
| `pg_write_all_data` | 14+ | `INSERT`/`UPDATE`/`DELETE` на все таблицы/представления/последовательности + `USAGE` на все схемы (аналогично без `BYPASSRLS`) |
| `pg_database_owner` | 14+ | Неявный единственный член — владелец текущей БД; изначально владеет схемой `public` |
| `pg_signal_backend` | 10+ | Отмена запроса / завершение чужой сессии (`pg_cancel_backend`, `pg_terminate_backend`); **не** может сигналить бэкенды суперпользователя |
| `pg_read_server_files` / `pg_write_server_files` / `pg_execute_server_program` | 15+ | `COPY` из/в любые файлы и запуск программ на сервере от имени пользователя СУБД — обходят проверки прав на уровне БД и могут дать уровень суперпользователя; выдавать только доверенным ролям |
| `pg_checkpoint` | 17+ | Выполнение `CHECKPOINT` |
| `pg_maintain` | 17+ | `VACUUM`, `ANALYZE`, `CLUSTER`, `REFRESH MATERIALIZED VIEW`, `REINDEX`, `LOCK TABLE` на всех таблицах (привилегия `MAINTAIN`) |
| `pg_use_reserved_connections` | 17+ | Использование слотов `reserved_connections` |
| `pg_create_subscription` | 18+ | `CREATE SUBSCRIPTION` при наличии `CREATE` на базе |

**Пример: роль для мониторинга** (подробности — в **[Наблюдаемости](./observability.md)**):

```sql
CREATE USER monitoring_user WITH PASSWORD 'strong_password';
GRANT pg_monitor TO monitoring_user;
GRANT CONNECT ON DATABASE mydb TO monitoring_user;
```

### Управление правами доступа (GRANT / REVOKE)

```sql
-- 1. Доступ к базе данных
GRANT CONNECT ON DATABASE mydb TO app_user;

-- 2. Доступ к схеме: USAGE — видеть/доступ к объектам, CREATE — создавать новые
GRANT USAGE ON SCHEMA public TO app_user;

-- 3. Доступ к таблицам (существующим)
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_write_role;

-- 4. Последовательности — обязательно для serial/identity-столбцов
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_write_role;

-- 5. Хранимые объекты
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_role;

-- Отзыв (например, запрет создания объектов в public для всех)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

### Права по умолчанию (Default Privileges)

Частая проблема: права выданы на существующие таблицы, но новые таблицы создаются без них. Решение — `ALTER DEFAULT PRIVILEGES`:

```sql
-- Выполняется от имени ПОЛЬЗОВАТЕЛЯ, который будет создавать таблицы
-- (или суперпользователем с FOR ROLE для конкретного создателя)
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO read_only_group;

ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO read_only_group;
```

Действует только на объекты, которые создаст указанная роль; для каждого создателя таблиц — своя запись.

### Наследование через групповые роли (рекомендуемый способ)

Права назначаются группе, пользователи включаются в группу:

```sql
-- 1. Права группе
GRANT SELECT ON TABLE my_table TO read_only_group;

-- 2. Группа пользователю
GRANT read_only_group TO app_user;

-- 3. Исключение пользователя из группы
REVOKE read_only_group FROM app_user;
```

### Тестирование прав через SET ROLE

```sql
SET ROLE app_user;                 -- «примерить» роль (требует членства с SET TRUE)
SELECT * FROM information_schema.role_table_grants WHERE grantee = 'app_user';
SELECT has_table_privilege('app_user', 'my_table', 'SELECT');
-- → t
RESET ROLE;
```

### Row-Level Security (RLS) — кратко

RLS ограничивает доступ к строкам таблицы в зависимости от вызывающей роли:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- Канонический паттерн: приложение задаёт текущего пользователя сессионной переменной
SET app.user_id = '42';
CREATE POLICY user_orders_policy ON orders
    FOR SELECT
    USING (user_id = current_setting('app.user_id')::int);
```

Ключевые моменты: владелец таблицы **не** подпадает под политики (подчинить — `ALTER TABLE orders FORCE ROW LEVEL SECURITY`); суперпользователи и `BYPASSRLS` обходят RLS; при включённом RLS без политик — default-deny; `USING` — какие строки видны, `WITH CHECK` — какие можно вставить/обновить. Полная механика (политики `ALL`/`SELECT`/`INSERT`/`UPDATE`/`DELETE`, restrictive/permissive, гонки в Read Committed, `security_invoker`-представления PG 15+, `row_security = off` для `pg_dump`) — в SSoT **[Row-Level Security](../Concepts/security_and_encryption.md)**.

### Маскирование PII

Динамическое маскирование (email, телефоны) для ролей аналитиков — расширение `postgresql-anonymizer`: **[Анонимизация и маскирование PII-данных](./anonymization.md)**.

### Пер-ролевые дефолты параметров

```sql
-- Принудительный statement_timeout для сервисной роли
ALTER ROLE app_user SET statement_timeout = '30s';
-- Только в конкретной базе
ALTER ROLE app_user IN DATABASE mydb SET search_path = 'app, public';
-- Сброс
ALTER ROLE app_user RESET statement_timeout;
```

### Пароли: задание, ротация, срок действия

```sql
ALTER USER app_user PASSWORD 'new_secure_pass';   -- эхо команды попадёт в историю!
\password app_user                                 -- безопасно: интерактивный ввод
ALTER ROLE app_user VALID UNTIL 'infinity';      -- снять истечение срока
```

Хэширование по `password_encryption` (дефолт `scram-sha-256` с PG 14; `md5` deprecated и будет удалён). Смена пароля действует для **новых** подключений, существующие сессии не разрываются — ротация без даунтайма. Миграция кластера md5 → SCRAM и переходный трюк с методом `md5` — в **[Безопасности](../Concepts/security_and_encryption.md)**. Внимание: md5-хэш использует имя роли как соль — после `ALTER ROLE ... RENAME` пароль сбрасывается.

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `CREATE ROLE` / `CREATE USER` | Создание роли / входящей роли | `CREATE USER app WITH LOGIN PASSWORD 'p';` |
| `ALTER ROLE` / `ALTER USER` | Изменение атрибутов, пароля, дефолтов | `ALTER ROLE app NOLOGIN;` |
| `DROP ROLE` / `dropuser` | Удаление (после `REASSIGN OWNED` + `DROP OWNED`) | `DROP ROLE old_user;` |
| `createdb` / `dropdb` | Создание / удаление базы | `sudo -u postgres createdb -O owner mydb` |
| `createuser` | CLI-обёртка над `CREATE ROLE` | `sudo -u postgres createuser -P -g grp app` |
| `\du` / `\du+` | Список ролей и атрибутов (+ описания) | `\du` |
| `\dp` (синоним `\z`) | Привилегии на объекты | `\z my_table` |
| `\password` | Смена пароля без открытого текста | `\password app_user` |
| `\drds` | Пер-ролевые дефолты параметров | `\drds` |
| `GRANT` / `REVOKE` | Выдача / отзыв привилегий и членств | `GRANT SELECT ON ALL TABLES IN SCHEMA public TO grp;` |
| `ALTER DEFAULT PRIVILEGES` | Права на будущие объекты | `ALTER DEFAULT PRIVILEGES FOR ROLE o IN SCHEMA public GRANT SELECT ON TABLES TO grp;` |
| `SET ROLE` / `RESET ROLE` | Переключение в роль в сессии | `SET ROLE app_user;` |
| `REASSIGN OWNED` / `DROP OWNED` | Передача / удаление объектов роли | `REASSIGN OWNED BY old TO new;` |

## Валидация и проверка

После настройки ролей и прав выполните проверки:

1. **Роли и их атрибуты:**
   ```sql
   \du
   -- или
   SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb,
          rolreplication, rolbypassrls, rolconnlimit
   FROM pg_roles WHERE rolname = 'app_user';
   ```
2. **Привилегии на конкретный объект:**
   ```sql
   \z my_table
   SELECT grantee, privilege_type
   FROM information_schema.role_table_grants
   WHERE table_name = 'my_table';
   ```
3. **Членства и опции:**
   ```sql
   SELECT m.member_roleid::regrole, r.rolname AS granted_role,
          m.admin_option, m.inherit_option, m.set_option
   FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.parent_roleid
   WHERE m.member_roleid = 'app_user'::regrole;
   ```
4. **Тест от имени роли:** `SET ROLE app_user;` → выполнить целевые запросы → `RESET ROLE;` (детали — выше).
5. **Лимит подключений:**
   ```sql
   SELECT usename, count(*) FROM pg_stat_activity
   WHERE usename = 'app_user' GROUP BY usename;
   ```
6. **Тестирование RLS:** подключитесь под ограниченным пользователем (или `SET ROLE`) и выполните `SELECT` — убедитесь, что возвращаются только разрешённые строки.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Permission denied для схемы public** | В PG 15+ у `PUBLIC` отозвано `CREATE` на схему `public` | `GRANT CREATE ON SCHEMA public TO role_name;` или создавайте отдельную схему |
| **Новые таблицы недоступны группе** | Не настроены `DEFAULT PRIVILEGES` | `ALTER DEFAULT PRIVILEGES FOR ROLE <создатель> ...` от имени создателя |
| **Роль не может войти в БД** | Нет `LOGIN`, нет записи в `pg_hba.conf`, нет `CONNECT` на базу | `ALTER ROLE ... LOGIN;`, проверить `pg_hba.conf` (reload), `GRANT CONNECT ON DATABASE` |
| **Не удаётся удалить роль** | Роль владеет объектами или выдавала привилегии | `REASSIGN OWNED BY old TO new;` и `DROP OWNED BY old;` — **в каждой базе кластера** (команды действуют только на текущую БД), затем `DROP ROLE` |
| **RLS не работает для владельца** | Владелец таблицы не подпадает под политики | `ALTER TABLE ... FORCE ROW LEVEL SECURITY;` |
| **Permission denied for sequence** | `serial`/`identity` требует `USAGE`/`SELECT` на последовательность | `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ...` + default privileges |
| **Permission denied for function** | `EXECUTE` отозван у `PUBLIC`/роли | `GRANT EXECUTE ON FUNCTION ... TO role;` |
| **FATAL: too many connections for role** | Достигнут `CONNECTION LIMIT` | Поднять лимит (`ALTER ROLE ... CONNECTION LIMIT n`), оптимизировать пулинг — [PgBouncer](./pgbouncer_setup.md) |
| **password authentication failed** | Несовместимость формата хэша (md5-хэш при методе `scram-sha-256`) | Сбросить пароль (`\password`), проверить `password_encryption` — [миграция](../Concepts/security_and_encryption.md) |
| **Пароль истёк при входе** | Достигнут `VALID UNTIL` | `ALTER ROLE ... VALID UNTIL 'infinity';` или новый пароль |
| **Аутентификация сломалась после RENAME** | md5-хэш привязан к имени роли (соль) | Задать пароль заново (`\password`) |

## Лучшие практики

- **Принцип наименьших привилегий:** отдельные роли для приложения, миграций, бэкапов и мониторинга; приложение — без `SUPERUSER`/`CREATEDB`/`CREATEROLE`; `CONNECTION LIMIT` для сервисных ролей.
- **Групповые роли вместо прямых грантов:** права — группам, пользователи — в группы; упрощает аудит и ротацию людей.
- **Пароли не в открытом виде:** `\password` или внешний secrets-менеджер, не SQL-строки в скриптах (попадают в логи и историю); регулярная ротация, `VALID UNTIL` для контрагентов.
- **`NOINHERIT` + `SET ROLE`** для сервисных аккаунтов, которым нужен эскалационный доступ только по требованию.
- **Не выдавайте права `PUBLIC`** глобально; не создавайте пользовательские объекты в схеме `public` (с PG 15 там нет `CREATE` у `PUBLIC`) — используйте отдельные схемы.
- **Предопределённые роли вместо `SUPERUSER`:** `pg_monitor` для мониторинга, `pg_maintain` для обслуживания, `pg_signal_backend` для отмены запросов; `pg_read/write_server_files` и `pg_execute_server_program` — только доверенным ролям (дают уровень суперпользователя).
- **Аудит:** периодически проверяйте `pg_roles` (атрибуты, `VALID UNTIL`), `pg_auth_members` (членства с `ADMIN`), `information_schema.role_table_grants`; DDL/ROLE-операции — через pgAudit (`pgaudit.log = 'role, ddl'`) — [аудит](../Concepts/security_and_encryption.md).
- **RLS:** `FORCE ROW LEVEL SECURITY` для владельца, `security_invoker`-представления вместо security-definer; бэкапы — с `row_security = off` (ошибка вместо молчаливого пропуска строк).

## Очистка и откат

```sql
-- 1. Передать объекты роли другому владельцу (выполнять в КАЖДОЙ базе!)
REASSIGN OWNED BY old_user TO new_admin;

-- 2. Удалить объекты, принадлежащие роли, и отозвать выданные ей привилегии
--    (тоже в КАЖДОЙ базе)
DROP OWNED BY old_user;

-- 3. Отозвать членства и привилегии, выданные роли
REVOKE read_only_group FROM old_user;
REVOKE SELECT ON TABLE my_table FROM old_user;

-- 4. Удалить роль
DROP ROLE old_user;
-- или из ОС:
-- sudo -u postgres dropuser old_user
```

Откат одного гранта: `REVOKE <привилегия> ON <объект> FROM <роль>;`. Откат дефолтных привилегий: `ALTER DEFAULT PRIVILEGES ... REVOKE ...`.

## Дополнительная информация

### Смежные темы

- **[Основы работы в psql](./console_basics.md)** — мета-команды инспекции ролей (`\du`, `\dp`, `\drds`, `\password`).
- **[Безопасность и шифрование](../Concepts/security_and_encryption.md)** — `pg_hba.conf`, SCRAM/md5, RLS (полная механика), TLS, аудит.
- **[Наблюдаемость PostgreSQL](./observability.md)** — роль `pg_monitor` и сбор метрик.
- **[Управление соединениями](./connection_management.md)** — таймауты, пулинг, `pg_stat_activity`.
- **[PgBouncer: установка и настройка](./pgbouncer_setup.md)** — динамическая аутентификация (`auth_query`) и роли для пула.
- **[Анонимизация и маскирование PII](./anonymization.md)** — `postgresql-anonymizer` и masked-роли.
- **[Безопасность хранимых объектов](../../Concepts/stored_objects/security.md)** — изоляция приложения через `SECURITY DEFINER`/`INVOKER` и роли.
- **[Управление инструментами](./management_tools.md)** — GUI и утилиты администрирования.
- **[Обзор PostgreSQL](../overview.md)** — архитектура и основные возможности.

### Официальная документация PostgreSQL

- [CREATE ROLE](https://www.postgresql.org/docs/current/sql-createrole.html) и [ALTER ROLE](https://www.postgresql.org/docs/current/sql-alterrole.html)
- [GRANT / REVOKE](https://www.postgresql.org/docs/current/sql-grant.html) (включая членство ролей и опции `ADMIN`/`SET`/`INHERIT`)
- [Predefined Roles](https://www.postgresql.org/docs/current/predefined-roles.html)
- [Role Attributes](https://www.postgresql.org/docs/current/role-attributes.html) и [Database Roles](https://www.postgresql.org/docs/current/database-roles.html)
- [ALTER DEFAULT PRIVILEGES](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html)
- [Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [createuser](https://www.postgresql.org/docs/current/app-createuser.html) / [createdb](https://www.postgresql.org/docs/current/app-createdb.html)
