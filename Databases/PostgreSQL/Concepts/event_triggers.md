# Event Triggers (триггеры событий DDL) в PostgreSQL

**Актуально для:** PostgreSQL 14–18

## Определения

*   **Event trigger** — триггер на событие DDL (CREATE/ALTER/DROP/REINDEX и др.), `DROP OWNED` или `TABLE REWRITE`, в отличие от обычных триггеров на DML (INSERT/UPDATE/DELETE). Глобален на уровне базы (не привязан к таблице).
*   **`ddl_command_start`** — событие, срабатывающее **до** выполнения DDL-команды. Позволяет запретить команду (через `RAISE EXCEPTION`).
*   **`ddl_command_end`** — событие **после** успешного выполнения DDL. Для аудита и логирования.
*   **`sql_drop`** — событие перед DROP объектов (после проверки зависимостей, до удаления).
*   **`table_rewrite`** — событие, когда команда требует перезаписи таблицы (ALTER TYPE и др.); позволяет запретить перезапись на горячих таблицах.
*   **`drop_owned`** — событие при выполнении `DROP OWNED` (PostgreSQL 16+).
*   **`login`** — событие при успешном подключении к базе данных (PostgreSQL 14+).
*   **`pg_event_trigger_ddl_commands()`** — функция в триггере на `ddl_command_end`: возвращает список объектов, затронутых командой (`command_tag`, `object_type`, `schema_name`, `object_name`, `object_identity`).
*   **`pg_event_trigger_dropped_objects()`** — функция в триггере на `sql_drop` и `drop_owned`: возвращает удаляемые объекты (`object_type`, `schema_name`, `object_name`, `all_dirty`).
*   **`pg_event_trigger_table_rewrite_relation()`** — функция в триггере на `table_rewrite`: возвращает информацию о таблице, которая должна быть перезаписана (`relname`, `schemaname`, `relid`, `command_tag`).
*   **`tg_tag`** — в функции: тег команды (`CREATE TABLE`, `ALTER TABLE`, `DROP INDEX`).
*   **`tg_loginuser`** — в функции на событие `login`: имя пользователя, выполинившего вход.
*   **`tg_loginremote`** — в функции на событие `login`: удалённый хост, с которого выполнено подключение.

## Предпосылки

1.  **Права**: `CREATE` на схему для функции; привилегия `EVENT TRIGGER` на базу для создания триггера (PostgreSQL 16+; в PG 14–15 только суперпользователь).
2.  **Язык**: `plpgsql` (в стандартной поставке).
3.  **Настройка логирования** для мониторинга блокировок: `log_error_verbosity = verbose` — выводит SQLSTATE, `DETAIL`, `HINT`, `CONTEXT` в серверный лог (см. [Конфигурацию наблюдаемости](../Operations/observability.md#конфигурация-для-глубокой-наблюдаемости)).
4.  **Исключение из CI/CD:** перед миграциями необходимо отключать event triggers, иначе миграционный инструмент (Flyway/Liquibase) упирается в запрет.

## Базовые концепции

### Чем event trigger отличается от pgAudit

*   **pgAudit** — расширение, логирует сессии/объекты в стандартный лог (см. [pgAudit](./extensions_utility.md#pgaudit)). Работает на уровне логирования, не влияет на выполнение.
*   **Event trigger** — нативный механизм, выполняет **код** (PL/pgSQL) в момент DDL. Может **запретить** команду (`RAISE EXCEPTION`), записать в таблицу аудита, уведомить. Не требует `shared_preload_libraries` и перезапуска.

Комбинация: pgAudit — для compliance-лога «кто что сделал», event trigger — для **контроля** («запретить DROP на production») и собственной таблицы аудита.

### Модель работы

1.  Клиент посылает DDL.
2.  PostgreSQL проверяет права.
3.  Срабатывает `ddl_command_start` (если есть event trigger) — можно запретить.
4.  Команда выполняется.
5.  Срабатывает `ddl_command_end` — аудит.
6.  Для DROP — `sql_drop` перед удалением.

Event trigger не может изменить DDL-команду (только запретить через `RAISE EXCEPTION`). Для временного отключения — `ALTER EVENT TRIGGER ... DISABLE`.

### Ограничения

*   `pg_event_trigger_ddl_commands()` доступна **только** в `ddl_command_end`; в `ddl_command_start` можно использовать только `tg_tag`.
*   `pg_event_trigger_dropped_objects()` доступна только в `sql_drop` и `drop_owned`.
*   `pg_event_trigger_ddl_commands()` пуст для некоторых команд (например, `COMMENT`) — проверяйте `tg_tag` и обрабатывайте пустой результат.
*   `sql_drop` срабатывает и для CASCADE — объекты, удаляемые каскадом, тоже видны в `pg_event_trigger_dropped_objects()` (с флагом `all_dirty = true`).
*   `table_rewrite` срабатывает не на каждый ALTER, а только на команды, требующие перезаписи (ALTER TYPE, ADD COLUMN с default в старых версиях PG); ADD COLUMN без default — без перезаписи.
*   Суперпользователь может отключить любой event trigger (`ALTER EVENT TRIGGER ... DISABLE`).
*   `DROP OWNED` — событие `drop_owned` (PG 16+), не путать с `sql_drop` (удаление отдельных объектов).
*   Порядок срабатывания нескольких event triggers на одно событие не гарантирован.
*   `WHEN TAG IN (...)` работает для `ddl_command_start`, `ddl_command_end`, `sql_drop`, `drop_owned`, но **не** для `table_rewrite` и `login`.
*   `login` event trigger срабатывает после аутентификации, но не может блокировать подключение через `RAISE EXCEPTION` (лучше использовать `pg_hba.conf` для ограничения доступа).
*   `pg_dump` не выполняет DDL (только читает каталог), поэтому триггеры не срабатывают во время `pg_dump`. При `pg_restore` DDL-команды выполняются, и event triggers срабатывают.
*   Не заменяет row-level security и права: запрещает только DDL, не DML.

## Справочник и операции

### События и функции

| Событие | Срабатывает | Доступные функции/переменные | `WHEN TAG IN` | Версия | Применение |
|---------|------------|------------------------------|---------------|--------|------------|
| `ddl_command_start` | До выполнения DDL | `tg_tag` | ✅ | PG 9.3+ | Блокировка DDL (RAISE EXCEPTION) |
| `ddl_command_end` | После DDL | `pg_event_trigger_ddl_commands()` | ✅ | PG 9.3+ | Аудит DDL |
| `sql_drop` | Перед удалением объектов | `pg_event_trigger_dropped_objects()` | ✅ | PG 9.3+ | Защита от DROP/CASCADE |
| `table_rewrite` | Перед перезаписью таблицы | `pg_event_trigger_table_rewrite_relation()` | ❌ | PG 9.3+ | Блокировка ALTER на горячих таблицах |
| `drop_owned` | При `DROP OWNED` | `pg_event_trigger_dropped_objects()` | ✅ | PG 16+ | Аудит массового удаления |
| `login` | При подключении к БД | `tg_loginuser`, `tg_loginremote` | ❌ | PG 14+ | Аудит подключений |

### Управление триггерами

```sql
-- Список event triggers (psql)
\dy
-- →                        List of configurations
--                          Name               |    Type    |  Owner   | Enabled
-- audit_ddl_on_end         | event trigger    | postgres   | O

-- или через SQL
SELECT evtname, evtevent, evtowner::regrole, evtenabled
FROM pg_event_trigger;
-- → audit_ddl_on_end | ddl_command_end | postgres | O

-- Отключить (например, на время миграции)
ALTER EVENT TRIGGER audit_ddl_on_end DISABLE;
-- → ALTER EVENT TRIGGER

-- Включить обратно
ALTER EVENT TRIGGER audit_ddl_on_end ENABLE;

-- Удалить
DROP EVENT TRIGGER IF EXISTS audit_ddl_on_end;
```

## Практические сценарии

### 1. Таблица аудита DDL

```sql
CREATE TABLE ddl_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    tag text NOT NULL,
    object_type text,
    schema_name text,
    object_name text,
    command_text text,
    user_name text NOT NULL DEFAULT current_user
);
```

### 2. Функция и триггер на `ddl_command_end`

```sql
CREATE OR REPLACE FUNCTION audit_ddl() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE obj record;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands()
    LOOP
        INSERT INTO ddl_audit (tag, object_type, schema_name, object_name, command_text)
        VALUES (tg_tag, obj.object_type, obj.schema_name, obj.object_name,
                tg_tag || ' ' || obj.object_identity);
    END LOOP;
END;
$$;

CREATE EVENT TRIGGER audit_ddl_on_end
    ON ddl_command_end
    EXECUTE FUNCTION audit_ddl();
```

Проверка:

```sql
CREATE TABLE demo_audit (id int);
SELECT tag, object_type, schema_name, object_name FROM ddl_audit ORDER BY id DESC LIMIT 1;
-- → CREATE TABLE | table | public | demo_audit
```

### 3. Запрет DROP на production (защита от случайного удаления)

```sql
CREATE OR REPLACE FUNCTION forbid_drop() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE obj record;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_dropped_objects()
    LOOP
        IF obj.object_type IN ('table', 'index', 'view')
           AND obj.schema_name NOT IN ('tmp', 'staging')
        THEN
            RAISE EXCEPTION 'DROP % % запрещён на production (объект: %.%)',
                obj.object_type, obj.object_name, obj.schema_name, obj.object_name
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
END;
$$;

CREATE EVENT TRIGGER forbid_drop_on_sql_drop
    ON sql_drop
    EXECUTE FUNCTION forbid_drop();
```

Проверка:

```sql
DROP TABLE demo_audit;
-- → ERROR: DROP table demo_audit запрещён на production (объект: public.demo_audit)
-- → SQLSTATE: 55000 (object_not_in_prerequisite_state)
```

### 4. Защита от перезаписи горячих таблиц (`table_rewrite`)

```sql
CREATE OR REPLACE FUNCTION forbid_rewrite_hot() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE obj record;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_table_rewrite_relation()
    LOOP
        IF obj.relname IN ('orders', 'payments') THEN
            RAISE EXCEPTION 'ALTER, требующий перезаписи таблицы %, запрещён в рабочее время',
                obj.relname;
        END IF;
    END LOOP;
END;
$$;

CREATE EVENT TRIGGER forbid_rewrite_hot_tables
    ON table_rewrite
    EXECUTE FUNCTION forbid_rewrite_hot();
```

### 5. Фильтрация по тегу команды (`WHEN TAG IN`)

```sql
-- Только аудит CREATE TABLE и DROP TABLE
CREATE EVENT TRIGGER audit_tables_only
    ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE', 'DROP TABLE')
    EXECUTE FUNCTION audit_ddl();
```

### 6. Аудит подключений (`login`, PostgreSQL 14+)

```sql
CREATE TABLE login_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login_time timestamptz NOT NULL DEFAULT clock_timestamp(),
    user_name name NOT NULL DEFAULT tg_loginuser,
    remote_addr text
);

CREATE OR REPLACE FUNCTION audit_login() RETURNS event_trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO login_audit (user_name, remote_addr)
    VALUES (tg_loginuser, tg_loginremote);
END;
$$;

CREATE EVENT TRIGGER audit_login
    ON login
    EXECUTE FUNCTION audit_login();
```

## Валидация и проверка

1.  **Проверка, что triggers созданы:**
    ```sql
    SELECT evtname, evtevent, evtenabled FROM pg_event_trigger;
    -- → audit_ddl_on_end | ddl_command_end | O
    ```
2.  **Проверка, что аудит работает:**
    ```sql
    CREATE TABLE validation_test (id int);
    SELECT count(*) > 0 FROM ddl_audit WHERE object_name = 'validation_test';
    -- → true
    ```
3.  **Проверка блокировки DDL:**
    ```sql
    DROP TABLE validation_test;
    -- → ERROR: ... запрещён на production
    ```
4.  **Проверка отключения для миграций:**
    ```sql
    ALTER EVENT TRIGGER audit_ddl_on_end DISABLE;
    SELECT evtenabled FROM pg_event_trigger WHERE evtname = 'audit_ddl_on_end';
    -- → D (disabled)
    ALTER EVENT TRIGGER audit_ddl_on_end ENABLE;
    ```
5.  **Проверка аудита логинов:**
    ```sql
    SELECT count(*) > 0 FROM login_audit WHERE user_name = current_user;
    -- → true (после подключения)
    ```

## Мониторинг и алерты (DevOps/SRE)

Event triggers обеспечивают мониторинг DDL, который стандартно не логируется (по умолчанию `log_statement = 'none'`).

1.  **Мониторинг DDL через таблицу аудита:**
    ```sql
    -- DDL-операции за последние 24 часа
    SELECT tag, count(*) FROM ddl_audit
    WHERE occurred_at > now() - interval '24 hours'
    GROUP BY tag ORDER BY 2 DESC;
    ```
2.  **Мониторинг блокировок DDL** (RAISE EXCEPTION попадает в серверный лог с SQLSTATE):
    - `log_error_verbosity = verbose` — выводит SQLSTATE, DETAIL, HINT, CONTEXT в лог
    - Лог-парсер должен отлавливать SQLSTATE `55000` (блокировка DDL) и другие коды защиты
    - См. [Конфигурацию наблюдаемости](../Operations/observability.md#конфигурация-для-глубокой-наблюдаемости)
3.  **Мониторинг аудита подключений:**
    ```sql
    -- Подключения из недоверенных сетей
    SELECT user_name, remote_addr, login_time
    FROM login_audit
    WHERE remote_addr NOT LIKE '10.%'
    ORDER BY login_time DESC LIMIT 10;
    ```
4.  **Алёрты (SRE):**
    - Рост `ddl_audit` > N записей/час — возможен неавторизованный DDL
    - DDL в production в ночное время (02:00–05:00) — требует проверки
    - Блокировка DDL с SQLSTATE `55000` в логах — миграция столкнулась с защитой, проверить отключены ли triggers
    - `login_audit` с `remote_addr` из недоверенных сетей — неавторизованный доступ
5.  **Интеграция с pgBadger:**
    - pgBadger анализирует серверный лог PostgreSQL (см. [Анализ логов](../Operations/observability.md#анализ-логов))
    - Event trigger с `RAISE EXCEPTION` создаёт запись в логе с SQLSTATE и сообщением
6.  **CI/CD интеграция:**
    - Перед миграциями: `ALTER EVENT TRIGGER ... DISABLE` (или временно DROP)
    - После миграций: `ALTER EVENT TRIGGER ... ENABLE`
    - Проверка: все triggers в статусе `O` (enabled) перед выпуском в production

## Устранение неисполнимостей и пограничные случаи

*   **Event trigger не срабатывает:** проверьте статус `evtenabled = 'O'` в `pg_event_trigger`; убедитесь, что выбранное событие поддерживается; проверьте привилегию `EVENT TRIGGER` на базу.
*   **`pg_event_trigger_ddl_commands()` пуст:** для некоторых команд (например, `COMMENT`) функция не возвращает объекты — обрабатывайте пустой результат, проверяйте `tg_tag`.
*   **`WHEN TAG IN (...)` не работает:** проверьте точное название тега (например, `CREATE TABLE`, а не `CREATE`); убедитесь, что событие поддерживает `WHEN TAG IN`.
*   **`table_rewrite` не срабатывает на каждый ALTER:** срабатывает только на команды, требующие перезаписи (ALTER TYPE, ADD COLUMN с default в старых версиях PG).
*   **`sql_drop` для CASCADE:** объекты, удаляемые каскадом, также видны с флагом `all_dirty = true`.
*   **Ошибка создания функции:** функция должна возвращать тип `event_trigger`, а не `trigger` — `CREATE OR REPLACE FUNCTION ... RETURNS event_trigger`.
*   **Суперпользователь обходит защиту:** `ALTER EVENT TRIGGER ... DISABLE` работает для суперпользователя — для строгой защиты используйте pgAudit или внешние средства (операционная политика, не только БД).
*   **`login` trigger не блокирует подключение:** `RAISE EXCEPTION` в `login` trigger не отклоняет подключение — используйте `pg_hba.conf` для блокировки.
*   **Производительность:** триггер на `ddl_command_end` добавляет минимальный оверхед (DDL — редкая операция). При высокой частоте DDL (например, во время миграций с сотнями команд) рекомендуется временно отключать триггер.

## Лучшие практики

1.  **`ddl_command_end` для аудита, `sql_drop` для защиты от удаления, `table_rewrite` для защиты горячих таблиц** — выбирайте событие под задачу.
2.  **`RAISE EXCEPTION` в `ddl_command_start`/`sql_drop`** — единственный нативный способ запретить DDL без правки приложения.
3.  **Фильтруйте по схеме** — не запрещайте DDL в `tmp`/`staging`/миграционных схемах, иначе сломаете CI/CD. Используйте `WHEN TAG IN (...)` для сужения, а внутри функции — проверку `obj.schema_name`.
4.  **Аудит в отдельную таблицу** — при `DROP DATABASE` event trigger не спасёт; для критичного аудита — pgAudit в лог или внешний collector.
5.  **Отключайте на время миграций** (`ALTER EVENT TRIGGER ... DISABLE`) — иначе миграционный инструмент (Flyway/Liquibase) упирается в запрет.
6.  **Не дублируйте pgAudit:** pgAudit — compliance-лог, event trigger — контроль и собственная таблица. Оба могут работать одновременно.
7.  **Для CI/CD:** автоматизируйте отключение/включение triggers через скрипты миграций.

## Очистка и откат

1.  **Отключить все event triggers:**
    ```sql
    DO $$
    DECLARE r record;
    BEGIN
        FOR r IN SELECT evtname FROM pg_event_trigger
        LOOP
            EXECUTE format('ALTER EVENT TRIGGER %I DISABLE', r.evtname);
        END LOOP;
    END $$;
    ```
2.  **Удалить triggers:**
    ```sql
    DROP EVENT TRIGGER IF EXISTS audit_ddl_on_end;
    DROP EVENT TRIGGER IF EXISTS audit_tables_only;
    DROP EVENT TRIGGER IF EXISTS forbid_drop_on_sql_drop;
    DROP EVENT TRIGGER IF EXISTS forbid_rewrite_hot_tables;
    DROP EVENT TRIGGER IF EXISTS audit_login;
    ```
3.  **Удалить функции:**
    ```sql
    DROP FUNCTION IF EXISTS audit_ddl();
    DROP FUNCTION IF EXISTS forbid_drop();
    DROP FUNCTION IF EXISTS forbid_rewrite_hot();
    DROP FUNCTION IF EXISTS audit_login();
    ```
4.  **Очистить таблицы аудита:**
    ```sql
    TRUNCATE ddl_audit RESTART IDENTITY;
    TRUNCATE login_audit RESTART IDENTITY;
    -- или
    DROP TABLE IF EXISTS ddl_audit;
    DROP TABLE IF EXISTS login_audit;
    ```
5.  **Восстановить привилегии:** если создавали роль с `EVENT TRIGGER`:
    ```sql
    REVOKE EVENT TRIGGER ON DATABASE your_db FROM deploy_user;
    ```

## Дополнительная информация

*   [pgAudit (расширение)](./extensions_utility.md#pgaudit) — расширенный аудит DDL.
*   [Ограничения](./constraints.md) — EXCLUSION и CHECK.
*   [Миграции схем](./schema_migrations.md) — expand-contract, online DDL.
*   [Роли и базы данных](../Operations/role_management.md) — привилегия MAINTAIN, pg_maintain.
*   [Безопасность и шифрование](./security_and_encryption.md) — аудит доступа, шифрование.
*   [Наблюдаемость PostgreSQL](../Operations/observability.md) — `log_error_verbosity`, pgBadger, logrotate, алертинг.
*   [Консольные основы](../Operations/console_basics.md) — `\dy` (список event triggers).
*   [Отладка хранимых объектов](./stored_objects_debugging.md) — `log_error_verbosity`, `VERBOSITY verbose`.
*   [Официальная документация: event triggers](https://www.postgresql.org/docs/current/event-triggers.html)
