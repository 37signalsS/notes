# Troubleshooting и ограничения хранимых объектов

**Актуально для:** PostgreSQL 17/18, MariaDB 10.11/11.4, MySQL 8.4 LTS

## Определения

**Бесконечная рекурсия триггеров** — состояние, при котором триггер вызывает операцию, которая снова активирует тот же или другой триггер, создавая цикл, завершающийся ошибкой стека или взаимной блокировкой.

**Блокировка строк** — механизм обеспечения согласованности, при котором сессия удерживает эксклюзивный доступ к строке до завершения транзакции. В контексте хранимых объектов возникает при `SELECT ... FOR UPDATE` или `INSERT` в другую таблицу из триггера.

**FOR UPDATE SKIP LOCKED** — вариант блокировки строк в PostgreSQL, при котором строки, уже заблокированные другими сессиями, пропускаются вместо ожидания освобождения.

**statement_timeout** — параметр PostgreSQL, задающий максимальную длительность выполнения любого оператора в миллисекундах. Значение `0` (по умолчанию) отключает таймаут.

**transaction_timeout** — параметр PostgreSQL (17+), завершающий сессию, если транзакция длится дольше указанного времени в миллисекундах. Действует и на неявную транзакцию одного оператора; на prepared-транзакции не распространяется.

**lock_timeout** — параметр PostgreSQL, задающий максимальное время ожидания получения блокировки в миллисекундах. Значение `0` (по умолчанию) отключает таймаут.

**max_stack_depth** — параметр PostgreSQL, задающий максимальную безопасную глубину стека выполнения в килобайтах. По умолчанию `2048` (2 MB). Превышение глубины вызывает ошибку `stack depth limit exceeded`.

**max_execution_time** — параметр MySQL, задающий максимальное время выполнения оператора в миллисекундах. Значение `0` (по умолчанию) отключает таймаут. Важное ограничение: действует **только на read-only `SELECT`** и, по документации, **игнорируется для `SELECT` внутри stored programs** — то есть на таймаут процедуры, функции, триггера или события не влияет.

**max_statement_time** — параметр MariaDB, задающий максимальное время выполнения оператора в секундах. Значение `0` (по умолчанию) отключает таймаут. В отличие от MySQL, действует на все типы запросов, но с тем же ключевым исключением: **не распространяется на операторы внутри stored procedures**, а значит, и на события.

**innodb_lock_wait_timeout** — параметр MySQL/MariaDB InnoDB, задающий время ожидания получения row-level блокировки в секундах. По умолчанию `50`.

**lock_wait_timeout** — параметр MySQL/MariaDB, задающий время ожидания metadata lock в секундах. MySQL: по умолчанию `31536000` (1 год). MariaDB: по умолчанию `86400` (1 день).

**SECURITY DEFINER** — режим выполнения хранимого объекта PostgreSQL, при котором он запускается с привилегиями владельца функции. Подробнее: [Безопасность хранимых объектов](security.md).

**DEFINER** — аналог `SECURITY DEFINER` в MariaDB/MySQL. Подробнее: [Безопасность хранимых объектов](security.md).

## Основные концепции

### Транзакционный контекст хранимых объектов

Хранимые объекты (процедуры, функции, триггеры, события) выполняются в рамках транзакции вызывающего сеанса. Это означает:

- **Наследование блокировок:** если вызывающая транзакция удерживает блокировки, хранимый объект работает в том же изоляционном уровне.
- **Откат при ошибке:** любая необработанная ошибка внутри хранимого объекта откатывает всю транзакцию вызывающего сеанса.
- **Видимость изменений:** `BEFORE` триггер видит данные до применения изменений; `AFTER` триггер видит изменения в рамках той же транзакции.

### Иерархия таймаутов

В PostgreSQL и MariaDB/MySQL существует несколько уровней таймаутов, которые взаимодействуют по иерархии:

**PostgreSQL:**
- `statement_timeout` прерывает оператор по истечении времени.
- `lock_timeout` прерывает ожидание блокировки, но не влияет на выполнение после получения блокировки.
- `transaction_timeout` (17+) прерывает всю транзакцию по истечении времени.
- Правило: если `statement_timeout` больше `lock_timeout`, то `lock_timeout` сработает первым при ожидании блокировки. Обратная постановка бессмысленна: при ненулевом `statement_timeout` установка равного или большего `lock_timeout` не даёт эффекта — оператор всё равно прервётся по `statement_timeout`.
- Правило приоритета: если `transaction_timeout` меньше или равен `idle_in_transaction_session_timeout` либо `statement_timeout`, то **более долгий таймаут игнорируется**. Например, `transaction_timeout = 60s` при `statement_timeout = 30s` не даёт никакой защиты — 30 секунд всё равно прервут оператор раньше. Таймаут, который вы хотите видеть срабатывающим, должен быть меньше остальных, а не больше.

**MariaDB/MySQL:**
- `max_statement_time` (MariaDB, секунды) прерывает запрос по времени; `max_execution_time` (MySQL, миллисекунды) — только read-only `SELECT`.
- **Ни один из них не ограничивает выполнение самого хранимого объекта:** MySQL игнорирует `max_execution_time` для `SELECT` внутри stored programs, а `max_statement_time` в MariaDB не действует на операторы внутри stored procedures. Практический вывод: длительность процедуры или события ограничивайте только изнутри тела или внешним планировщиком — см. [Практические сценарии](practical_scenarios.md).
- `innodb_lock_wait_timeout` прерывает ожидание row-level блокировки в InnoDB.
- `lock_wait_timeout` прерывает ожидание metadata lock.
- Риск: в MySQL `lock_wait_timeout` по умолчанию равен 1 году, что может привести к длительному зависанию DDL-операций.

### Ограничения стека и рекурсии

Стек выполнения — это область памяти, выделенная на каждый вызов хранимого объекта. При рекурсивных вызовах стек растёт. Когда глубина рекурсии превышает лимит, СУБД прерывает выполнение:

- **PostgreSQL:** `max_stack_depth` (по умолчанию 2 MB). Ошибка: `stack depth limit exceeded`.
- **MariaDB/MySQL:** Аналогичное ограничение реализовано на уровне движка без отдельного параметра конфигурации.

### Модель привилегий и наследование прав

Хранимые объекты не имеют собственных привилегий — они наследуют права владельца (`SECURITY DEFINER` / `DEFINER`) или вызывающего (`SECURITY INVOKER` / `INVOKER`). Контекст выполнения определяет, какие операции доступны объекту. Подробнее о модели привилегий: [Безопасность хранимых объектов](security.md).

## Практические сценарии

### Runbook: процедура зависла

**Ситуация:** Вызов хранимой процедуры не завершается, сессия находится в состоянии `active` неопределённо долго.

**Пошаговая диагностика:**

1. **Идентифицируйте зависшую сессию:**
   ```sql
   -- PostgreSQL
   SELECT pid, usename, datname, state, query_start, state_change, query
   FROM pg_stat_activity
   WHERE state = 'active'
     AND query NOT LIKE '%pg_stat_activity%';
   -- → pid | usename | datname | state  | query_start       | query
   -- → 1234| app_user | mydb    | active | 2026-10-01 10:00:00 | CALL long_proc()
   ```

   ```sql
   -- MariaDB/MySQL
   SHOW PROCESSLIST;
   -- → Id | User | Host | db | Command | Time | State | Info
   -- → 42 | app  | localhost | mydb | Query | 300 | Executing | CALL long_proc()
   ```

2. **Проверьте блокировки:**
   ```sql
   -- PostgreSQL
   SELECT * FROM pg_locks WHERE NOT granted;
   ```

   ```sql
   -- MySQL 8.0.1+ (MariaDB по-прежнему использует information_schema.innodb_lock_waits)
   SELECT * FROM sys.innodb_lock_waits;
   ```
   > **Версия важна:** `INFORMATION_SCHEMA.INNODB_LOCK_WAITS` удалена начиная с MySQL 8.0.1. На MySQL 8.4 используйте `sys.innodb_lock_waits` или `performance_schema.data_lock_waits`; в MariaDB представление `information_schema.innodb_lock_waits` остаётся штатным.

3. **Проверьте таймауты сессии:**
   ```sql
   -- PostgreSQL
   SHOW statement_timeout;
   -- → 0 (отключён)
   ```

   ```sql
   -- MariaDB/MySQL
   SHOW VARIABLES LIKE 'max_execution_time';
   -- → max_execution_time | 0
   ```

4. **Остановите сессию, если требуется:**
   ```sql
   -- PostgreSQL
   SELECT pg_terminate_backend(1234);
   -- → t
   ```

   ```sql
   -- MariaDB/MySQL
   KILL QUERY 42;
   -- → Query OK, 0 rows affected
   ```

5. **Проанализируйте причину:** проверьте логи на предмет бесконечного цикла, отсутствующего индекса или блокировки от другой сессии.

### Runbook: триггер вызвал рекурсию

**Ситуация:** Триггер вызывает операцию, которая активирует другой триггер, создавая бесконечный цикл.

**Действия:**
1. Остановите зависшие сессии через `pg_terminate_backend` / `KILL`.
2. Отключите триггер временно: `ALTER TABLE table_name DISABLE TRIGGER trigger_name;` (PostgreSQL) или сбросьте флаг (MariaDB/MySQL).
3. Внедрите защитный флаг в триггер (см. раздел «Типичные ошибки», пункт 1).

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
-- Рекомендуемый способ: pg_blocking_pids() сам находит блокирующие PID
SELECT a.pid AS blocked_pid,
       a.usename AS blocked_user,
       a.wait_event_type,
       a.wait_event,
       pg_blocking_pids(a.pid) AS blocking_pids,
       a.query AS blocked_statement,
       pg_blocking_pids(a.pid) AS blocking_pids,
       (SELECT query FROM pg_stat_activity s
         WHERE s.pid = ANY(pg_blocking_pids(a.pid))) AS blocking_statement
FROM pg_stat_activity a
WHERE cardinality(pg_blocking_pids(a.pid)) > 0;
-- → blocked_pid | blocked_user | wait_event_type | blocking_pids
-- → 4210       | app           | Lock             | {4208}
```

`pg_blocking_pids()` возвращает массив: блокирующих сессий может быть несколько, и они образуют цепочку. Функция корректно обрабатывает случаи, которые самосоединение `pg_locks` пропускает: soft-блокировки ожидания heavyweight-лока, а также блокировки, отданные параллельному воркеру (параллельный запрос) — в этих случаях самосоединение по `pg_locks` либо не находит блокирующего, либо находит неверного. Документация PostgreSQL рекомендует `pg_blocking_pids()` как штатный инструмент определения блокирующих.

Ручное самосоединение `pg_locks` по `locktype`/`relation` (альтернатива, встречающаяся в старых руководствах) оставить полезным не стоит: оно сопоставляет блокировки по совпадению объекта, а не по факту блокировки, поэтому даёт ложные пары при нескольких ожиданиях на одной таблице.

**Диагностика (MariaDB):**

```sql
-- MariaDB: information_schema.innodb_lock_waits остаётся актуальным
SELECT * FROM information_schema.innodb_lock_waits;
```

**Диагностика (MySQL 8.4):**

```sql
-- Готовый запрос из документации MySQL
SELECT
  r.trx_id                AS waiting_trx_id,
  r.trx_mysql_thread_id   AS waiting_thread,
  r.trx_query             AS waiting_query,
  b.trx_id                AS blocking_trx_id,
  b.trx_mysql_thread_id   AS blocking_thread,
  b.trx_query             AS blocking_query
FROM performance_schema.data_lock_waits w
INNER JOIN information_schema.innodb_trx b
  ON b.trx_id = w.blocking_engine_transaction_id
INNER JOIN information_schema.innodb_trx r
  ON r.trx_id = w.requesting_engine_transaction_id;
```

Сопоставление колонок при миграции с `INNODB_LOCK_WAITS` (документировано MySQL):

| `INNODB_LOCK_WAITS` (до 8.0.1) | `data_lock_waits` (8.0.1+) |
|---|---|
| `REQUESTING_TRX_ID` | `REQUESTING_ENGINE_TRANSACTION_ID` |
| `REQUESTED_LOCK_ID` | `REQUESTING_ENGINE_LOCK_ID` |
| `BLOCKING_TRX_ID` | `BLOCKING_ENGINE_TRANSACTION_ID` |
| `BLOCKING_LOCK_ID` | `BLOCKING_ENGINE_LOCK_ID` |

Проще использовать `sys.innodb_lock_waits` — представление уже выполняет это соединение и отдаёт готовые `waiting_pid`/`blocking_pid`. Разрешения на него другие: `data_lock_waits` требует `SELECT` на самой таблице Performance Schema, тогда как `INNODB_LOCK_WAITS` требовала глобальную привилегию `PROCESS`.

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

### 7. Порядок срабатывания триггеров не гарантиован

**Проблема:** На одну таблицу повешено несколько триггеров на одно событие. Порядок их выполнения не определён.

**PostgreSQL:** Триггеры выполняются в алфавитном порядке имён.

**MariaDB/MySQL:** Порядок не гарантирован.

**Решение:** Если порядок важен — используйте именование триггеров с префиксами (`01_`, `02_`, `03_`) или объедините логику в одну триггерную функцию.

---

### 8. Процедура зависла (таймаут не сработал)

**Проблема:** Вызов хранимой процедуры не завершается indefinitely.

**Симптомы:**
- Сессия в `pg_stat_activity` / `SHOW PROCESSLIST` находится в состоянии `active` неопределённо долго.
- Другие сессии ожидают блокировки, удерживаемой зависшей сессией.

**Причины:**
1. `statement_timeout = 0` (отключён) и процедура содержит бесконечный цикл.
2. Ожидание блокировки без `lock_timeout` / `innodb_lock_wait_timeout`.
3. Долгий оператор без защиты `max_execution_time` / `max_statement_time`.

**Диагностика (PostgreSQL):**

```sql
-- Проверка активных сессий
SELECT pid, usename, datname, state, query_start, state_change, query
FROM pg_stat_activity
WHERE state = 'active'
  AND query NOT LIKE '%pg_stat_activity%';

-- Проверка блокировок
SELECT * FROM pg_locks WHERE NOT granted;

-- Проверка таймаута сессии
SHOW statement_timeout;
-- → 0 (отключён)
```

**Диагностика (MariaDB/MySQL):**

```sql
-- Проверка активных сессий
SHOW PROCESSLIST;

-- Проверка блокировок
SELECT * FROM information_schema.innodb_lock_waits;

-- Проверка таймаутов
SHOW VARIABLES LIKE 'max_execution_time';
SHOW VARIABLES LIKE 'innodb_lock_wait_timeout';
```

**Решение:**
1. **Установите локальный таймаут:** `SET LOCAL statement_timeout = '5s';` (PostgreSQL) или `SET MAX_EXECUTION_TIME = 5000;` (MySQL) в начале процедуры.
2. **Остановите сессию:** `SELECT pg_terminate_backend(pid);` (PostgreSQL) или `KILL QUERY thread_id;` (MariaDB/MySQL).
3. **Проанализируйте причину:** проверьте логи на предмет бесконечного цикла, отсутствующего индекса или блокировки от другой сессии.

### 9. Событие выполняется дважды: на источнике и на реплике (MariaDB/MySQL)

**Проблема:** событие, созданное на источнике репликации, выполняется и на
реплике — Maintenance-задача дублируется, а операции, не идемпотентные
(начисление, отправка уведомления, ротация), дают двойной эффект.

**Почему это происходит:** событие, созданное на источнике, реплицируется на
реплику. Признать это поведение штатным позволяет сам синтаксис определения
события: для события на реплике существует отдельный статус
`DISABLE ON REPLICA` — он указывает, что событие было создано на источнике
репликации и реплицировано на реплику, но на реплике не выполняется.
`DISABLE ON REPLICA` заменяет ранее использовавшееся `DISABLE ON SLAVE`,
которое устарело и подлежит удалению.

**Диагностика:**

```sql
-- Статус события: ON REPLICA означает «создано на источнике, не выполнять здесь»
SELECT SCHEMA_NAME, EVENT_NAME, STATUS, INTERVAL_VALUE, INTERVAL_FIELD, STARTS
FROM INFORMATION_SCHEMA.EVENTS
WHERE STATUS LIKE '%REPLICA%';
```

```text
-- → SCHEMA_NAME | EVENT_NAME          | STATUS
-- → shop        | nightly_maintenance  | DISABLE ON REPLICA
```

**Решение:** определять события сразу с нужным статусом — либо выполнять
везде (идемпотентная операция), либо только на источнике:

```sql
CREATE EVENT nightly_maintenance
ON SCHEDULE EVERY 1 DAY
DISABLE ON REPLICA
DO DELETE FROM sessions WHERE last_seen < NOW() - INTERVAL 30 DAY;
```

**Дополнительная ловушка того же класса:** при переходе 5.7 → 8.0 значение по
умолчанию `event_scheduler` меняется с `OFF` на `ON`. После обновления события,
которые годами лежали в базе выключенными, начинают выполняться. Проверяйте
список событий до обновления:

```sql
SELECT SCHEMA_NAME, EVENT_NAME, STATUS FROM INFORMATION_SCHEMA.EVENTS;
```

**Смежная ловушка репликации для триггеров:** statement-based репликация имеет
известные проблемы с хранимыми процедурами и функциями и триггерами;
документация прямо рекомендует использовать row-based репликацию, чтобы их
избежать. Проверьте формат бинарного лога, прежде чем рассчитывать на
корректную работу объектов в реплицированной схеме.

### 10. Курсор в процедуре теряет блокировки после `COMMIT` (PostgreSQL)

**Симптомы:** процедура с `COMMIT` внутри `FOR ... IN SELECT ... LOOP` работает без
ошибок, но параллельные операции, которые раньше блокировались этой процедурой,
теперь проходят одновременно. Никаких сообщений об ошибке в логах нет.

**Причина:** обычно курсоры автоматически закрываются при коммите. Но курсор,
созданный в цикле, при первом же `COMMIT` или `ROLLBACK` автоматически
преобразуется в holdable-курсор: запрос курсора вычисляется **целиком** при первом
`COMMIT`, а не построчно. Сам курсор удаляется автоматически после выхода из
цикла, поэтому изменение почти невидимо. Но блокировки таблиц и строк,
которые держал запрос курсора, **после первого `COMMIT` уже не удерживаются**.

То есть процедура формально работает, а защита от конкурентного изменения
исчезает ровно в тот момент, когда вы считаете, что транзакция зафиксирована.

**Диагностика:** сравните план и фактические блокировки до и после первого
коммита в цикле; проверьте, нет ли в теле `ORDER BY` или `FOR UPDATE`, которые
и удерживали блокировки:

```sql
SELECT pid, locktype, relation::regclass, mode, granted
FROM pg_locks
WHERE relation IS NOT NULL AND NOT granted
ORDER BY pid;
```

**Решение:** не полагаться на блокировки курсора как на механизм изоляции.
Варианты по возрастанию строгости:

1. Обрабатывать порцию данных до коммита, а не коммитить внутри цикла по каждой строке.
2. Вынести выборку в отдельную фазу (зафиксировать идентификаторы строк), затем
   работать с ними в цикле с явными коммитами.
3. Если блокировки действительно нужны, брать их явно через `FOR UPDATE` внутри
   каждой итерации, а не полагаться на неявные блокировки курсора.

Два смежных ограничения той же механики:

- **Управление транзакциями невозможно, если между вызовами есть посторонняя
  команда.** При стеке `CALL proc1() -> CALL proc2() -> CALL proc3()` вторая и
  третья процедуры управлять транзакциями могут, а при стеке
  `CALL proc1() -> SELECT func2() -> CALL proc3()` — уже нет: `SELECT` разрывает
  цепочку. Проверяйте стек вызовов, если процедура «вдруг» перестала делать
  `COMMIT`.
- **В цикле по не read-only курсору управление транзакциями запрещено**, например
  в цикле по `UPDATE ... RETURNING`.

### 11. Объект работает на primary, но падает на standby (PostgreSQL)

**Симптомы:** на primary процедура отрабатывает, на standby — ошибка
`cannot execute INSERT in a read-only transaction` либо `recovery is in progress`,
хотя логика объекта корректна.

**Причина:** в режиме hot standby все соединения строго read-only — временные
таблицы тоже нельзя записывать. Транзакции, начатые в hot standby, никогда не
получают transaction ID и не пишут в WAL. Это ограничение распространяется даже
на временные таблицы, поскольку без transaction ID нельзя ни прочитать, ни
записать строку.

Запрещённые операции перечислены документацией явно:

| Категория | Запрещено в hot standby |
|---|---|
| DML | `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `COPY FROM`, `TRUNCATE` |
| DDL | `CREATE`, `DROP`, `ALTER`, `COMMENT` |
| Блокировки | режим выше `ROW EXCLUSIVE`; короткая форма `LOCK` (запрашивает `ACCESS EXCLUSIVE`) |
| Транзакции | `BEGIN`/`START TRANSACTION READ WRITE`, `SET TRANSACTION READ WRITE`, `SET transaction_read_only = off` |
| Двухфазный коммит | `PREPARE TRANSACTION`, `COMMIT PREPARED`, `ROLLBACK PREPARED` |
| Последовательности | `nextval()`, `setval()` |
| Уведомления | `LISTEN`, `NOTIFY` (`UNLISTEN` разрешён) |

Отдельно важно для диагностики триггеров: **во время recovery нет разрешённых
действий, приводящих к срабатыванию триггера**. Поэтому триггер на standby не
выполнится, даже если операция формально разрешена.

**Диагностика:**

```sql
-- PG 16+: прямое состояние standby для сессии
SHOW in_hot_standby;
-- → in_hot_standby = on

-- Состояние сервера и режим восстановления
SELECT pg_is_in_recovery();
-- → t (сервер в standby)
```

**Решение:** определить, относится ли объект к read-only сценарию.

1. **Пометить функцию `STABLE` или `IMMUTABLE`,** если она только читает данные:
   ```sql
   ALTER FUNCTION app.get_customer_stats(INTEGER) STABLE;
   ```
   Это не только отражает семантику, но и сообщает планировщику, что результат
   зависит только от аргументов и снапшота запроса, а не от текущего времени или
   внешнего состояния.
2. **Разнести ветки:** read-only версия для отчётов на standby, write-версия
   для primary. Проверка `pg_is_in_recovery()` внутри функции — рабочий, но
   явный костыль; лучше разделить объекты по имени.
3. **Вынести запись за пределы БД**, если она действительно нужна: записи в
   удалённую базу через `dblink` и другие операции вне базы через PL-функции
   остаются возможными даже при локально read-only транзакции. Для планирования
   этого поведения явно предусмотрите деградацию при потере связи.

**Смежная ловушка:** сессии, пережившие переключение, остаются подключёнными —
после завершения hot standby в них можно начать read-write транзакции, даже если
сессия была создана во время standby. Поэтому код, полагающийся на «мы на
standby», должен проверять состояние явно, а не считать его постоянным.

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
| Таймаут оператора | `statement_timeout` (мс, по умолчанию 0) | `max_execution_time` (мс, по умолчанию 0) / `max_statement_time` (с, по умолчанию 0) | `SET LOCK_TIMEOUT` (мс, по умолчанию -1) |

## Типичные ограничения

1. **Триггер не может содержать DDL** (в большинстве СУБД). Исключение — PostgreSQL `event triggers` для DDL-событий.
2. **Триггер не может модифицировать ту же таблицу** (в MySQL/MariaDB вызовет ошибку или бесконечную рекурсию в `BEFORE` триггере).
3. **Функция не может выполнить DDL** (`CREATE TABLE`, `ALTER TABLE` и т.д.) в PostgreSQL (исключение — `SECURITY DEFINER` функции).
4. **Событие не может подключиться к удалённой БД** — выполняется только локально.
5. **Триггер `BEFORE DELETE` не может вернуть `NULL`** в PostgreSQL — будет ошибка.
6. **Порядок срабатывания триггеров** не гарантирован при нескольких триггерах на одно событие (зависит от алфавитного порядка имён в PostgreSQL).
7. **Пропущенные аргументы** в MariaDB/MySQL: если процедура имеет параметры по умолчанию, при вызове нужно указывать все предыдущие.
8. **Лимит вложенности хранимых вызовов:** PostgreSQL — `max_stack_depth` (по умолчанию 2 MB стека), MariaDB — аналогичное ограничение.
9. **Привилегии на триггеры:** В PostgreSQL для создания триггера необходима привилегия `TRIGGER` на таблице, а не только `EXECUTE` на функции.
10. **Отсутствие общего таймаута в SQL Server:** SQL Server не имеет параметра, эквивалентного `statement_timeout` для локальных запросов. Доступен только `SET LOCK_TIMEOUT` для блокировок.

## Лучшие практики

1. **Настройте on-call runbook для зависших процедур:** первый шаг — проверка блокировок (`pg_locks`, `innodb_lock_waits`), второй — проверка таймаутов (`statement_timeout`, `max_execution_time`), третий — принудительная остановка сессии (`pg_terminate_backend`, `KILL QUERY`).
2. **Устанавливайте `statement_timeout` на уровне роли, а не глобально:** это позволяет задавать разные таймауты для OLTP и OLAP-нагрузок без влияния на системные операции.
3. **Коррелируйте метрики:** при росте количества активных сессий проверяйте одновременно CPU, Disk I/O и блокировки — проблема может быть не в коде процедуры, а в ресурсах.
4. **Алертируйте на `active` сессии дольше порога:** например, `state = 'active' AND query_start < now() - interval '5 minutes'` в PostgreSQL или `Time > 300` в `SHOW PROCESSLIST`.
5. **Документируйте порядок эскалации:** если процедура зависает более 3 раз в неделю — эскалация в команду разработки с приложением логов и плана выполнения.
6. **Версионируйте хранимые объекты в Git:** используйте инструменты миграций (Atlas, Sqitch, Liquibase) для деплоя. Никогда не изменяйте объекты напрямую в production.
7. **Тестируйте откат:** перед деплоем критичной процедуры проверьте, что `ROLLBACK` выполняется корректно и не оставляет частично изменённых данных.
8. **Используйте `SECURITY INVOKER` по умолчанию:** переключайтесь на `SECURITY DEFINER` / `DEFINER` только когда логика объективно требует прав владельца. Подробнее: [Безопасность хранимых объектов](security.md).

## Дополнительная информация

### См. также

- **[Безопасность хранимых объектов](security.md)** — модель привилегий, SECURITY DEFINER, динамический SQL.
- **[Мониторинг хранимых объектов](monitoring.md)** — `pg_stat_user_functions`, `pg_stat_statements`, Performance Schema.
- **[Ключевые концепции производительности БД](../database_performance_concepts.md)** — USE-методология, Baseline, Troubleshooting паттерны.
- **[Конкурентность и блокировки в PostgreSQL](../../PostgreSQL/Concepts/concurrency_and_locking.md)** — MVCC, уровни изоляции, deadlock detection.
- **[Управление хранимыми объектами в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)** — отладка, Event Scheduler, SIGNAL/RESIGNAL.
- **[Отладка объектов в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md)** — техники профилирования и поиска ошибок.
