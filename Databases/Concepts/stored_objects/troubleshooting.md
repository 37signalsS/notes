# Troubleshooting и ограничения хранимых объектов

## Типичные ошибки

### 1. Бесконечная рекурсия триггеров

**Проблема:** Триггер вызывает операцию, которая активирует другой триггер, который снова активирует первый.

**Симптомы:**

PostgreSQL:
```
ERROR: stack depth limit exceeded
HINT: Increase the configuration parameter "max_stack_depth"
```

MariaDB/MySQL:
```
ERROR 1442 (HY000): Can't update table 'X' in stored function/trigger/...
because it is already used by statement which invoked this stored function/trigger
```

**Решение (PostgreSQL):**

```sql
-- Проверка рекурсии через session setting
CREATE OR REPLACE FUNCTION fn_safe_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF current_setting('app.audit_in_progress', true) = '1' THEN
        RETURN NEW;
    END IF;

    PERFORM set_config('app.audit_in_progress', '1', true);

    INSERT INTO audit_log (table_name, operation, new_data)
    VALUES (TG_TABLE_NAME, TG_OP, row_to_json(NEW)::JSONB);

    PERFORM set_config('app.audit_in_progress', '0', true);
    RETURN NEW;
END;
$$;
```

**Решение (MariaDB/MySQL):**

```sql
DELIMITER //
CREATE TRIGGER trg_safe_audit
BEFORE INSERT ON orders
FOR EACH ROW
BEGIN
    IF @audit_running IS NULL OR @audit_running = 0 THEN
        SET @audit_running = 1;
        INSERT INTO audit_log (table_name, operation, new_data)
        VALUES ('orders', 'INSERT', JSON_OBJECT('id', NEW.id, 'total', NEW.total));
        SET @audit_running = 0;
    END IF;
END //
DELIMITER ;
```

**Профилактика:**
- Триггер не должен модифицировать ту же таблицу, на которой он определён.
- Используйте `AFTER` триггеры вместо `BEFORE` для операций чтения/записи в другие таблицы.
- Избегайте DDL внутри триггеров.

---

### 2. Блокировка строк в триггере

**Проблема:** Триггер выполняет `SELECT ... FOR UPDATE` или `INSERT` в другую таблицу, что вызывает блокировки и таймауты.

**Диагностика (PostgreSQL):**

```sql
-- Проверка текущих блокировок
SELECT
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.relation = blocked_locks.relation
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

**Диагностика (MariaDB/MySQL):**

```sql
-- Просмотр текущих блокировок
SELECT
    r.trx_id AS waiting_trx,
    r.trx_mysql_thread_id AS waiting_thread,
    r.trx_query AS waiting_query,
    b.trx_id AS blocking_trx,
    b.trx_mysql_thread_id AS blocking_thread,
    b.trx_query AS blocking_query
FROM information_schema.innodb_lock_waits w
JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id;
```

**Решение:**
- Используйте `FOR UPDATE SKIP LOCKED` вместо `FOR UPDATE` в триггерах — это пропустит заблокированные строки.
- Минимизируйте количество SQL-операций внутри триггера.
- Не выполняйте долгие запросы в триггере — это блокирует все операции на таблице.

---

### 3. Объект не найден при вызове

**Проблема:** `function ... does not exist` или `procedure ... does not exist`.

**Причины:**
1. Объект создан в другой схеме (и не добавлен в `search_path`).
2. Типы параметров не совпадают (PostgreSQL чувствителен к типам).
3. Пользователь не имеет права `EXECUTE`.
4. Объект был удалён или переименован.

**Диагностика (PostgreSQL):**

```sql
-- Поиск объекта по имени
SELECT routine_name, routine_type, specific_name, external_language
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name LIKE '%order%';
-- → routine_name         | routine_type | specific_name | external_language
-- → ---------------------+--------------+---------------+------------------
-- → update_order_status  | PROCEDURE    | ...           | plpgsql
-- → get_order_summary    | FUNCTION     | ...           | sql

-- Проверка search_path
SHOW search_path;
-- → search_path
-- → ----------------
-- → "$user", public

-- Проверка прав
SELECT grantee, privilege_type
FROM information_schema.role_routine_grants
WHERE routine_name = 'update_order_status';
-- → grantee | privilege_type
-- → --------+---------------
-- → app_role| EXECUTE
```

**Диагностика (MariaDB/MySQL):**

```sql
-- Поиск процедуры/функции
SELECT routine_name, routine_type, routine_schema
FROM information_schema.routines
WHERE routine_name LIKE '%order%';
-- → routine_name         | routine_type | routine_schema
-- → ---------------------+--------------+----------------
-- → update_order_status  | PROCEDURE    | mydb

-- Проверка прав
SHOW GRANTS FOR 'app_user'@'%';
```

**Решение:** Указывайте полное имя схемы (`schema_name.function_name`) или добавьте схему в `search_path`.

---

### 4. Event Scheduler выключен (MariaDB/MySQL)

**Проблема:** События создаются, но не выполняются.

**Диагностика:**

```sql
SHOW VARIABLES LIKE 'event_scheduler';
-- → Variable_name     | Value
-- → ------------------+-------
-- → event_scheduler    | OFF
```

**Решение:**

```sql
-- Включение (требуется SUPER или EVENT privilege)
SET GLOBAL event_scheduler = ON;

-- Для сохранения после перезапуска добавить в my.cnf:
-- [mysqld]
-- event_scheduler=ON
```

---

### 5. Триггер не видит данные, вставленные в той же транзакции (PostgreSQL)

**Проблема:** `BEFORE` триггер не может прочитать данные, которые ещё не вставлены.

**Симптом:** Запрос в `BEFORE INSERT` триггере возвращает пустой результат.

**Решение:** Используйте `NEW` для чтения вставляемых данных:

```sql
CREATE OR REPLACE FUNCTION fn_validate_order()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- NEW содержит данные, которые будут вставлены
    IF NEW.total < 0 THEN
        RAISE EXCEPTION 'Стоимость заказа не может быть отрицательной: %', NEW.total;
    END IF;

    -- Если нужна проверка связанных данных:
    IF NOT EXISTS (SELECT 1 FROM customers WHERE id = NEW.customer_id) THEN
        RAISE EXCEPTION 'Клиент % не найден', NEW.customer_id;
    END IF;

    RETURN NEW;
END;
$$;
```

---

### 6. Невозможно выполнить DDL в функции (PostgreSQL)

**Проблема:** Попытка выполнить `CREATE TABLE`, `ALTER TABLE` и т.д. внутри функции вызывает ошибку.

```
ERROR: CREATE DATABASE is not allowed in a SQL function
```

**Причина:** PostgreSQL запрещает DDL в обычных функциях для защиты от непредвиденных изменений схемы.

**Решение:**
- Используйте `dblink` для выполнения DDL в отдельном подключении.
- Используйте `SECURITY DEFINER` функции с осторожностью.
- Для миграций схемы используйте инструменты миграций (Flyway, Liquibase).

---

### 7. Порядок срабатывания триггеров не гарантирован

**Проблема:** На одну таблицу повешено несколько триггеров на одно событие. Порядок их выполнения не определён.

**PostgreSQL:** Триггеры выполняются в алфавитном порядке имён.

**MariaDB/MySQL:** Порядок не гарантирован.

**Решение:** Если порядок важен — используйте именование триггеров с префиксами (`01_`, `02_`, `03_`) или объедините логику в одну триггерную функцию.

---

## Ограничения по СУБД

| Особенность | PostgreSQL | MariaDB/MySQL | SQL Server |
|---|---|---|---|
| `COMMIT` внутри процедуры | Да (`PROCEDURE`) | Да | Да |
| Триггер на представлении | `INSTEAD OF` | Нет | `INSTEAD OF` |
| Триггер на DDL | Да (event triggers) | Нет | DDL триггеры |
| Вложенность триггеров | Ограничена `max_stack_depth` | Ограничена | Ограничена |
| Пакетная обработка | `FOR UPDATE SKIP LOCKED` | `LIMIT` в подзапросе | `TOP ... WITH (ROWLOCK)` |
| Динамический SQL | `EXECUTE` (PL/pgSQL) | Prepared statements | `sp_executesql` |
| Табличные функции | `RETURNS SETOF` / `RETURNS TABLE` | `RETURNS TABLE` | Table-valued functions |
| Триггеры на `TRUNCATE` | Да | Нет | Да |
| Возврат `NULL` из `BEFORE DELETE` | Ошибка | Ошибка | Ошибка |

## Типичные ограничения

1. **Триггер не может содержать DDL** (в большинстве СУБД). Исключение — PostgreSQL `event triggers` для DDL-событий.
2. **Триггер не может модифицировать ту же таблицу** (в MySQL/MariaDB вызовет ошибку или бесконечную рекурсию в `BEFORE` триггере).
3. **Функция не может выполнить DDL** (`CREATE TABLE`, `ALTER TABLE` и т.д.) в PostgreSQL (исключение — `SECURITY DEFINER` функции).
4. **Событие не может подключиться к удалённой БД** — выполняется только локально.
5. **Триггер `BEFORE DELETE` не может вернуть `NULL`** в PostgreSQL — будет ошибка.
6. **Порядок срабатывания триггеров** не гарантирован при нескольких триггерах на одно событие (зависит от алфавитного порядка имён в PostgreSQL).
7. **Пропущенные аргументы** в MariaDB/MySQL: если процедура имеет параметры по умолчанию, при вызове нужно указывать все предыдущие.
8. **Лимит вложенности хранимых вызовов:** PostgreSQL — `max_stack_depth` (по умолчанию 2MB стека), MariaDB — аналогичное ограничение.
9. **Привилегии на триггеры:** В PostgreSQL для создания триггера необходима привилегия `TRIGGER` на таблице, а не только `EXECUTE` на функции.
