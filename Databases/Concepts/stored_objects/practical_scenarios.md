# Практические сценарии: хранимые объекты

**Актуально для:** PostgreSQL 17/18, MariaDB 10.11/11.4, MySQL 8.4 LTS

## Определения

**Аудит изменений (Change Data Capture через триггер)** — механизм логирования операций `INSERT`, `UPDATE`, `DELETE` на уровне строк с помощью `AFTER` триггера, записывающий старое и новое состояние в таблицу аудита.

**Пакетная обработка (Batch Processing)** — разбиение большой задачи на небольшие порции (батчи) с промежуточным `COMMIT`, чтобы ограничить время удержания блокировок и размер транзакции.

**Вычисляемая функция (Deterministic Function)** — функция, результат которой зависит только от входных параметров и не имеет побочных эффектов (`IMMUTABLE` в PostgreSQL, `DETERMINISTIC` в MariaDB/MySQL). Позволяет СУБД кэшировать результат и использовать функцию в индексах.

**Событие (Event / Scheduled Event)** — хранимый объект, выполняющийся по расписанию без внешнего планировщика (`Event Scheduler` в MariaDB/MySQL, `pg_cron` в PostgreSQL).

**Агрегатная синхронизация** — поддержание актуальной денормализованной статистики (счётчики, суммы) через триггеры на операции с исходными данными.

**Валидация данных на уровне БД** — принудительная проверка бизнес-правил в `BEFORE` триггере, предотвращающая запись некорректных данных независимо от источника (приложение, ручной `INSERT`).

---

## Основные концепции

### Где хранимые объекты работают как часть SRE-практик

В контексте эксплуатации хранимые объекты решают три класса задач:

1. **Автоматизация без вмешательства приложения** — ротация логов, синхронизация агрегатов, проверка данных. Такие объекты должны быть идемпотентными и иметь логирование для on-call.
2. **Безопасная пакетная обработка** — миграции данных, пересчёт метрик. Критично: ограничение размера транзакции, `SKIP LOCKED` для параллелизма, промежуточный `COMMIT`.
3. **Аудит и соответствие** — триггеры на запись изменений. Требуют: изолированная таблица аудита, неблокирующая вставка, политика Retention.

### Принципы проектирования сценариев

- **Идемпотентность:** повторный запуск процедуры/события не ломает данные.
- **Обратимость:** для каждого сценария должен быть план отката (drop trigger, truncate audit table, restore aggregates).
- **Изоляция:** аудит и служебные таблицы находятся в отдельном tablespace или схеме (PostgreSQL) / базе (MariaDB), чтобы не конкурировать за ресурсы с рабочими таблицами.
- **Наблюдаемость:** каждый запуск оставляет след в логах или служебной таблице.

---

## Практические сценарии

### Сценарий 1: Аудит изменений данных (триггер)

**Задача:** Автоматически логировать все изменения в таблице `employees` (кто, когда, что изменил).

#### Предварительные требования

- Права `CREATE` на схему/базу, `TRIGGER` на таблицу `employees`, `INSERT` на таблицу аудита.
- Таблица аудита должна находиться в отдельном tablespace/schema, если объём записей ожидается высоким.
- Для production: включите `log_statement = 'ddl'` (PostgreSQL) или `general_log` (MariaDB) для отслеживания создания триггеров.

#### PostgreSQL

```sql
-- Таблица аудита
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_data JSONB,
    new_data JSONB,
    changed_by TEXT DEFAULT current_user,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Функция-обработчик
CREATE OR REPLACE FUNCTION fn_audit_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO audit_log (table_name, operation, old_data, new_data)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD)::JSONB END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW)::JSONB END
    );
    RETURN COALESCE(NEW, OLD);
END;
$$;

-- Привязка к таблице
CREATE TRIGGER trg_audit_employees
AFTER INSERT OR UPDATE OR DELETE ON employees
FOR EACH ROW
EXECUTE FUNCTION fn_audit_trigger();
```

**Проверка:**

```sql
INSERT INTO employees (name, department, salary) VALUES ('Иванов И.И.', 'IT', 85000);
UPDATE employees SET salary = 90000 WHERE name = 'Иванов И.И.';
DELETE FROM employees WHERE name = 'Иванов И.И.';

SELECT * FROM audit_log;
-- → id | table_name  | operation | old_data | new_data | changed_by | changed_at
-- → ----+-------------+-----------+----------+----------+------------+-----------
-- →   1 | employees   | INSERT    | null     | {...}    | admin      | 2025-01-15
-- →   2 | employees   | UPDATE    | {...}    | {...}    | admin      | 2025-01-15
-- →   3 | employees   | DELETE    | {...}    | null     | admin      | 2025-01-15
```

#### MariaDB/MySQL

```sql
CREATE TABLE audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(64) NOT NULL,
    operation VARCHAR(10) NOT NULL,
    old_data JSON,
    new_data JSON,
    changed_by VARCHAR(100) DEFAULT CURRENT_USER(),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DELIMITER //
CREATE TRIGGER trg_audit_employees_insert
AFTER INSERT ON employees
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, operation, new_data)
    VALUES ('employees', 'INSERT', JSON_OBJECT(
        'id', NEW.id,
        'name', NEW.name,
        'department', NEW.department,
        'salary', NEW.salary
    ));
END //

CREATE TRIGGER trg_audit_employees_update
AFTER UPDATE ON employees
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, operation, old_data, new_data)
    VALUES ('employees', 'UPDATE',
        JSON_OBJECT('id', OLD.id, 'name', OLD.name, 'salary', OLD.salary),
        JSON_OBJECT('id', NEW.id, 'name', NEW.name, 'salary', NEW.salary)
    );
END //

CREATE TRIGGER trg_audit_employees_delete
AFTER DELETE ON employees
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, operation, old_data)
    VALUES ('employees', 'DELETE', JSON_OBJECT(
        'id', OLD.id, 'name', OLD.name, 'department', OLD.department
    ));
END //
DELIMITER ;
```

#### Валидация

- Вставка/обновление/удаление в `employees` не возвращает ошибок.
- В `audit_log` появились строки с соответствующими `operation`.
- `changed_by` совпадает с текущим пользователем сессии.

#### Откат

```sql
-- PostgreSQL
DROP TRIGGER trg_audit_employees ON employees;
DROP FUNCTION fn_audit_trigger();

-- MariaDB/MySQL
DROP TRIGGER trg_audit_employees_insert;
DROP TRIGGER trg_audit_employees_update;
DROP TRIGGER trg_audit_employees_delete;
```

#### Замечания для SRE

- Таблица `audit_log` быстро растёт: настройте партиционирование по `changed_at` (PostgreSQL declarative partitioning, MariaDB `PARTITION BY RANGE`).
- Для предотвращения рекурсии при использовании `SECURITY DEFINER` см. [Безопасность хранимых объектов](security.md).
- Настройте алерт на рост размера `audit_log` свыше ожидаемого дневного объёма.

---

### Сценарий 2: Пакетная обработка (процедура)

**Задача:** Безопасно обработать миллионы записей небольшими порциями, чтобы не перегружать БД и не блокировать другие сессии.

#### Предварительные требования

- Права `CREATE PROCEDURE`, `UPDATE` на целевую таблицу.
- Включите `statement_timeout` (PostgreSQL) или `max_statement_time` (MariaDB) / `max_execution_time` (MySQL) на уровне сессии, чтобы предотвратить зависание. Учтите, что оба последних параметра не действуют на операторы внутри хранимого объекта — для самой процедуры таймаут задаётся внутри тела (`SET LOCAL statement_timeout` в PostgreSQL, `SET SESSION max_statement_time` в начале тела процедуры в MariaDB/MySQL).
- Для production: запускайте процедуру из под управляемого пользователя с ограниченными правами.

#### PostgreSQL

```sql
CREATE OR REPLACE PROCEDURE batch_update_status(
    p_old_status TEXT,
    p_new_status TEXT,
    p_batch_size INT DEFAULT 5000
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_total INT := 0;
    v_batch INT;
BEGIN
    LOOP
        WITH batch AS (
            SELECT id
            FROM orders
            WHERE status = p_old_status
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED  -- Пропускаем заблокированные строки
        )
        UPDATE orders
        SET status = p_new_status,
            updated_at = NOW()
        FROM batch
        WHERE orders.id = batch.id;

        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_total := v_total + v_batch;

        EXIT WHEN v_batch = 0;

        -- Даём другим сессиям поработать
        PERFORM pg_sleep(0.1);
        COMMIT;

        RAISE NOTICE 'Обработано: % (всего: %)', v_batch, v_total;
    END LOOP;

    RAISE NOTICE 'Готово. Всего обновлено: %', v_total;
END;
$$;

-- Вызов
CALL batch_update_status('pending', 'processing', 1000);
-- → NOTICE: Обработано: 1000 (всего: 1000)
-- → NOTICE: Обработано: 1000 (всего: 2000)
-- → NOTICE: Обработано: 347 (всего: 2347)
-- → NOTICE: Готово. Всего обновлено: 2347
```

**Ключевые моменты:**
- `FOR UPDATE SKIP LOCKED` — пропускает строки, заблокированные другими сессиями (параллельная обработка).
- `COMMIT` внутри процедуры — промежуточные изменения видны другим сессиям.
- `pg_sleep(0.1)` — пауза между батчами для снижения нагрузки.

#### MariaDB/MySQL

```sql
DELIMITER //
CREATE PROCEDURE batch_update_status(
    IN p_old_status VARCHAR(50),
    IN p_new_status VARCHAR(50),
    IN p_batch_size INT
)
BEGIN
    DECLARE v_total INT DEFAULT 0;
    DECLARE v_batch INT;

    batch_loop: LOOP
        -- Обработка порции
        UPDATE orders
        SET status = p_new_status, updated_at = NOW()
        WHERE id IN (
            SELECT id FROM (
                SELECT id FROM orders
                WHERE status = p_old_status
                LIMIT p_batch_size
            ) AS batch
        );

        SET v_batch = ROW_COUNT();
        SET v_total = v_total + v_batch;

        IF v_batch = 0 THEN
            LEAVE batch_loop;
        END IF;

        COMMIT;
        SELECT CONCAT('Обработано: ', v_batch, ' (всего: ', v_total, ')') AS progress;

        -- Пауза между порциями
        DO SLEEP(0.1);
    END LOOP;

    SELECT CONCAT('Готово. Всего обновлено: ', v_total) AS result;
END //
DELIMITER ;

-- Вызов
CALL batch_update_status('pending', 'processing', 1000);
```

#### Валидация

- После запуска проверьте, что количество обновлённых строк совпадает с ожидаемым: `SELECT COUNT(*) FROM orders WHERE status = 'processing' AND updated_at > NOW() - INTERVAL '1 hour'`.
- Убедитесь, что нет зависших транзакций. PostgreSQL — `SELECT * FROM pg_locks WHERE NOT granted`; MariaDB — `SELECT * FROM information_schema.innodb_lock_waits`. В MySQL 8.4 это представление удалено (см. ниже), используйте `performance_schema.data_lock_waits`.
  ```sql
  -- MySQL 8.0.1+ (MariaDB здесь по-прежнему использует innodb_lock_waits)
  SELECT * FROM performance_schema.data_lock_waits;
  ```
- Проверьте, что `v_total` в выводе совпадает с разностью `COUNT(*)` до и после.

#### Откат

Если обработка выполнена с ошибкой или нужно откатить статусы:

```sql
-- PostgreSQL: откат на основе времени или явного списка ID
UPDATE orders
SET status = 'pending', updated_at = NOW()
WHERE status = 'processing'
  AND updated_at >= '2025-01-15 02:00:00';

-- MariaDB/MySQL: аналогично
UPDATE orders
SET status = 'pending', updated_at = NOW()
WHERE status = 'processing'
  AND updated_at >= '2025-01-15 02:00:00';
```

#### Замечания для SRE

- Запускайте процедуру в окно низкой нагрузки ( maintenance window ), если таблица `orders` критична для интерактивных запросов.
- Настройте `statement_timeout` на уровне роли, чтобы процедура не зависла при проблемах с блокировками. См. [Troubleshooting хранимых объектов](troubleshooting.md).
- Для идемпотентности добавьте проверку: если батч уже обработан (есть метка в служебной таблице), пропустите его.

#### Защита от параллельного запуска (advisory lock)

Пакетная процедура, запущенная дважды одновременно, делит таблицу пополам
между двумя сессиями и удваивает нагрузку. `FOR UPDATE SKIP LOCKED` в теле
защищает от блокировок на уровне строк, но не от того, что **две** процедуры
пройдут одну и ту же логику с самого начала. Advisory lock решает это на
уровне сессии:

```sql
CREATE OR REPLACE PROCEDURE batch_update_status_guarded(
    p_old_status TEXT,
    p_new_status TEXT,
    p_batch_size INT DEFAULT 5000
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_lock_key BIGINT := 7398451;  -- произвольное, но стабильное число
    v_locked BOOLEAN;
BEGIN
    -- xact_lock: ожидание блокировки. pg_try_advisory_lock — неблокирующая версия
    v_locked := pg_try_advisory_xact_lock(v_lock_key);
    IF NOT v_locked THEN
        RAISE NOTICE 'Обработка уже выполняется в другой сессии — выход';
        RETURN;
    END IF;

    CALL batch_update_status(p_old_status, p_new_status, p_batch_size);
END;
$$;
```

Три варианта, которые важно различать:

| Функция | Когда освобождается | Поведение |
|---|---|---|
| `pg_try_advisory_xact_lock` | конец транзакции | неблокирующая, подходит для проверки «занято ли» |
| `pg_advisory_xact_lock` | конец транзакции | блокирующая, ждёт освобождения |
| `pg_try_advisory_lock` / `pg_advisory_lock` | явно, через `pg_advisory_unlock` | сессионная, переживает коммиты |

Для процедуры с `COMMIT` внутри тела выбор между первыми двумя критичен:
`xact_lock`-варианты освобождаются при **каждом** коммите внутри цикла, поэтому
между батчами блокировка снимается. Если нужна блокировка на всё время задания —
берите сессионную (`pg_try_advisory_lock`) и освобождайте её вручную в блоке
обработки исключений.

В MariaDB эквивалент — `GET_LOCK('имя', таймаут)` и `RELEASE_LOCK`, которые
действуют на уровне соединения, а не сервера: соединение с пулом (proxy, ORM)
может закрыться, и блокировка исчезнет.

#### Уведомление о завершении: `pg_notify` и пул соединений

Один из типовых приёмов — сигнализировать приложению о завершении пакета:

```sql
PERFORM pg_notify('batch_complete', json_build_object(
    'batch_id', v_total,
    'finished_at', NOW()
)::text);
```

Здесь есть ограничение, которое ломает ожидания чаще всего: **`pg_notify`
работает только в session pooling**, а не в transaction pooling. При
transaction pooling клиент возвращается в пул сразу после `COMMIT`, и
уведомление доставляется соединению, которое к этому моменту может
обслуживать другого клиента. Уведомление не потеряется (оно попадёт в
очередь), но будет доставлено не тому клиенту.

Практические варианты:

- `LISTEN`/`NOTIFY` в PgBouncer требуют session pooling — см.
  [Настройка PgBouncer](../../PostgreSQL/Operations/pgbouncer_setup.md).
- Для надёжной доставки используйте таблицу-очередь с записью в той же
  транзакции, что и данные, и опросом по расписанию; это работает при любом
  режиме пулинга.
- Проверить фактическое состояние пула можно так:
  ```sql
  SHOW POOLS;   -- в psql-режиме PgBouncer
  -- → cl_active | cl_waiting | maxwait
  ```

---

### Сценарий 3: Вычисляемые данные (функция)

**Задача:** Функция для расчёта стоимости доставки на основе веса, расстояния и уровня клиента.

#### Предварительные требования

- Права `CREATE FUNCTION`.
- В PostgreSQL: параметр `search_path` должен включать схему с функцией.
- В MariaDB/MySQL: требуется привилегия `EXECUTE` на функцию.

```sql
CREATE OR REPLACE FUNCTION calculate_shipping_cost(
    p_weight_kg NUMERIC,
    p_distance_km NUMERIC,
    p_customer_level TEXT DEFAULT 'standard'
) RETURNS NUMERIC
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT ROUND(
        (p_weight_kg * 0.5 + p_distance_km * 0.1)
        * CASE p_customer_level
            WHEN 'premium' THEN 0.7
            WHEN 'gold' THEN 0.85
            ELSE 1.0
          END,
        2
    );
$$;

-- Использование в запросе
SELECT
    order_id,
    weight,
    distance,
    calculate_shipping_cost(weight, distance, 'gold') AS shipping_cost
FROM pending_shipments;
-- → order_id | weight | distance | shipping_cost
-- → ---------+--------+----------+--------------
-- → 1        | 2.5    | 100      | 53.13
-- → 2        | 0.5    | 50       | 13.28
```

#### Табличная функция (PostgreSQL)

```sql
-- Функция, возвращающая набор строк
CREATE OR REPLACE FUNCTION get_orders_by_status(
    p_status TEXT
) RETURNS TABLE (
    order_id INT,
    customer_name TEXT,
    total NUMERIC,
    created_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
AS $$
    SELECT o.id, c.name, o.total, o.created_at
    FROM orders o
    JOIN customers c ON c.id = o.customer_id
    WHERE o.status = p_status
    ORDER BY o.created_at DESC;
$$;

-- Использование
SELECT * FROM get_orders_by_status('pending');
-- → order_id | customer_name | total  | created_at
-- → ---------+---------------+--------+-----------
-- → 42       | Иванов        | 1500.00| 2025-01-15
-- → 38       | Петров        |  800.00| 2025-01-14
```

#### Функция вычисления возраста (MariaDB)

```sql
DELIMITER //
CREATE FUNCTION calculate_age(p_birthdate DATE)
RETURNS INT
DETERMINISTIC  -- Аналог IMMUTABLE в PostgreSQL
BEGIN
    DECLARE v_age INT;
    SET v_age = TIMESTAMPDIFF(YEAR, p_birthdate, CURDATE());
    RETURN v_age;
END //
DELIMITER ;

-- Использование
SELECT name, calculate_age(birthdate) AS age FROM employees;
-- → name    | age
-- → --------+---
-- → Иванов  | 32
-- → Петров  | 28
```

#### Валидация

- Функция возвращает одинаковые значения для одинаковых входных параметров (проверка `IMMUTABLE`/`DETERMINISTIC`).
- В PostgreSQL: `SELECT proname, provolatile FROM pg_proc WHERE proname = 'calculate_shipping_cost';` — должно быть `i` (immutable).
- В MariaDB: `SHOW FUNCTION STATUS WHERE Name = 'calculate_age';` — `Dt_type` должен быть `deterministic`.

#### Замечания для SRE

- `IMMUTABLE` функции могут использоваться в индексах (PostgreSQL expression indexes). При изменении логики функции удалите и пересоздайте индекс.
- `STABLE` функции безопасны для использования в `WHERE` clause запросов.
- Не используйте `IMMUTABLE` для функций, зависящих от времени (`NOW()`, `CURDATE()`), настроек роли или поиска в таблицах — это сломает оптимизатор.

---

### Сценарий 4: Ротация логов (событие)

**Задача:** Ежедневно удалять записи старше 90 дней из таблицы логов.

#### Предварительные требования

- Права `CREATE EVENT` (MariaDB/MySQL) или суперпользователь для `pg_cron` (PostgreSQL).
- В MariaDB/MySQL: `event_scheduler = ON` в конфигурационном файле. Дефолты различаются: в MySQL 8.0 значение по умолчанию — `ON`, в MariaDB — `OFF`, поэтому задавайте его явно.
- Таблица логов должна иметь индекс на `created_at` для быстрого удаления.

#### MariaDB/MySQL

```sql
CREATE EVENT evt_rotate_access_logs
ON SCHEDULE EVERY 1 DAY
STARTS CONCAT(CURDATE() + INTERVAL 1 DAY, ' 03:00:00')
ON COMPLETION PRESERVE
ENABLE
COMMENT 'Ротация логов доступа: удаление записей старше 90 дней'
DO
BEGIN
    DECLARE v_deleted INT;

    DELETE FROM access_logs
    WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);

    SET v_deleted = ROW_COUNT();

    INSERT INTO admin_log (action, details, created_at)
    VALUES ('log_rotation', CONCAT('Удалено записей: ', v_deleted), NOW());
END;
```

#### PostgreSQL (pg_cron)

```sql
-- Установка расширения (требуется суперпользователь)
CREATE EXTENSION pg_cron;

-- Периодическая задача: очистка каждую ночь в 2:00
SELECT cron.schedule(
    'cleanup-access-logs',   -- Имя задачи
    '0 2 * * *',             -- CRON-выражение
    $$DELETE FROM access_logs WHERE created_at < NOW() - INTERVAL '30 days'$$
);

-- Проверка расписания
SELECT * FROM cron.job;
-- → jobid | schedule  | command                          | nodename | ...
-- → -------+-----------+----------------------------------+----------+--
-- →      1 | 0 2 * * * | DELETE FROM access_logs WHERE... | *        |
```

#### Валидация

- MariaDB/MySQL: `SHOW EVENTS LIKE 'evt_rotate_access_logs';` — статус `ENABLED`.
- PostgreSQL: `SELECT * FROM cron.job WHERE jobname = 'cleanup-access-logs';` — `schedule` и `command` корректны.
- Ручной запуск: выполните `DELETE` с тем же `WHERE` и проверьте, что удалено ожидаемое количество строк.
- Проверьте, что `event_scheduler = ON` (MariaDB/MySQL): `SHOW VARIABLES LIKE 'event_scheduler';`.

#### Откат

```sql
-- MariaDB/MySQL
DROP EVENT evt_rotate_access_logs;

-- PostgreSQL
SELECT cron.unschedule(1);
```

#### Замечания для SRE

- События выполняются в фоне без интерактивного сеанса: ошибки могут быть не видны. Добавьте `INSERT` в таблицу логов (как в примере) или `RAISE LOG` (PostgreSQL) для отслеживания.
- Для больших таблиц используйте партиционирование по `created_at` и `DROP PARTITION` вместо `DELETE` — это значительно быстрее и не создаёт bloat.
- Настройте алерт на рост размера таблицы `access_logs` свыше ожидаемого, если событие не срабатывает.
- `pg_cron` требует суперпользовательские права; в окружении с ограниченными привилегиями используйте внешний планировщик (cron + `psql`/`mysql` CLI) с ключом `.my.cnf`/`.pgpass` для аутентификации.

---

### Сценарий 5: Синхронизация агрегатов (триггер)

**Задача:** При добавлении/удалении заказа автоматически обновлять агрегированную статистику клиента.

#### Предварительные требования

- Права `CREATE TRIGGER`, `CREATE FUNCTION` на схему.
- Таблица `customer_stats` должна иметь первичный ключ на `customer_id`.
- Для high-volume workloads: рассмотрите пакетное обновление вместо триггера (см. Сценарий 2).

```sql
-- Таблица агрегатов
CREATE TABLE customer_stats (
    customer_id INT PRIMARY KEY,
    order_count INT DEFAULT 0,
    total_spent NUMERIC DEFAULT 0,
    last_order_at TIMESTAMPTZ
);

-- Триггерная функция
CREATE OR REPLACE FUNCTION fn_sync_customer_stats()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO customer_stats (customer_id, order_count, total_spent, last_order_at)
        VALUES (NEW.customer_id, 1, NEW.total, NOW())
        ON CONFLICT (customer_id) DO UPDATE SET
            order_count = customer_stats.order_count + 1,
            total_spent = customer_stats.total_spent + EXCLUDED.total_spent,
            last_order_at = EXCLUDED.last_order_at;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        UPDATE customer_stats
        SET order_count = order_count - 1,
            total_spent = customer_stats.total_spent - OLD.total
        WHERE customer_id = OLD.customer_id;
        RETURN OLD;
    END IF;
END;
$$;

-- Привязка
CREATE TRIGGER trg_sync_stats_insert
AFTER INSERT ON orders
FOR EACH ROW
EXECUTE FUNCTION fn_sync_customer_stats();

CREATE TRIGGER trg_sync_stats_delete
AFTER DELETE ON orders
FOR EACH ROW
EXECUTE FUNCTION fn_sync_customer_stats();

-- Проверка
INSERT INTO orders (customer_id, total) VALUES (1, 500.00);
INSERT INTO orders (customer_id, total) VALUES (1, 300.00);
DELETE FROM orders WHERE id = 1;

SELECT * FROM customer_stats WHERE customer_id = 1;
-- → customer_id | order_count | total_spent | last_order_at
-- → ------------+-------------+-------------+---------------
-- → 1           | 1           | 300.00      | 2025-01-15
```

#### Валидация

- Вставка и удаление заказов не вызывают ошибок.
- `customer_stats.order_count` и `total_spent` соответствуют агрегату по `orders` для данного `customer_id`.
- При массовом `DELETE FROM orders WHERE customer_id = 1` агрегат также скорректирован.

#### Откат

```sql
-- PostgreSQL
DROP TRIGGER trg_sync_stats_insert ON orders;
DROP TRIGGER trg_sync_stats_delete ON orders;
DROP FUNCTION fn_sync_customer_stats();

-- Пересчёт агрегата с нуля (если данные в stats повреждены)
UPDATE customer_stats cs
SET order_count = sub.cnt, total_spent = sub.total
FROM (
    SELECT customer_id, COUNT(*) AS cnt, COALESCE(SUM(total), 0) AS total
    FROM orders
    GROUP BY customer_id
) sub
WHERE cs.customer_id = sub.customer_id;
```

#### Замечания для SRE

- Триггеры на высоконагружаемых таблицах (`INSERT` > 1000 rps) добавляют латентность к каждой записи. Если задержка критична — перейдите на пакетное обновление (см. Сценарий 2) или materialized view с периодическим `REFRESH`.
- Настройте алерт на `order_count < 0` или `total_spent < 0` в `customer_stats` — это указывает на аномалию (например, откат транзакции после триггера без `REFERENCING OLD TABLE`).
- Для отладки проблем с триггерами используйте `pg_stat_user_functions` (PostgreSQL) или `performance_schema.events_statements_summary_by_program` (MariaDB/MySQL). См. [Мониторинг хранимых объектов](monitoring.md).

---

### Сценарий 6: Валидация данных на уровне БД (триггер)

**Задача:** Гарантировать, что все вставляемые/обновляемые данные соответствуют бизнес-правилам, независимо от источника (приложение, скрипт, ручной `INSERT`).

#### Предварительные требования

- Права `CREATE TRIGGER`, `CREATE FUNCTION`, `EXCEPTION` (PL/pgSQL) или `SIGNAL` (MariaDB/MySQL) в теле триггера.
- Правила валидации должны быть документированы в runbook для on-call.

#### PostgreSQL

```sql
CREATE OR REPLACE FUNCTION fn_validate_order_business_rules()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Правило 1: Стоимость заказа не может быть отрицательной
    IF NEW.total < 0 THEN
        RAISE EXCEPTION 'Стоимость заказа не может быть отрицательной: %', NEW.total;
    END IF;

    -- Правило 2: Клиент должен существовать
    IF NOT EXISTS (SELECT 1 FROM customers WHERE id = NEW.customer_id) THEN
        RAISE EXCEPTION 'Клиент % не найден', NEW.customer_id;
    END IF;

    -- Правило 3: Дата доставки не может быть в прошлом для новых заказов
    IF TG_OP = 'INSERT' AND NEW.delivery_date < CURRENT_DATE THEN
        RAISE EXCEPTION 'Дата доставки не может быть в прошлом: %', NEW.delivery_date;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_order
BEFORE INSERT OR UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION fn_validate_order_business_rules();
```

#### MariaDB/MySQL

```sql
DELIMITER //
CREATE TRIGGER trg_validate_order
BEFORE INSERT ON orders
FOR EACH ROW
BEGIN
    -- Правило 1: Стоимость не может быть отрицательной
    IF NEW.total < 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Стоимость заказа не может быть отрицательной';
    END IF;

    -- Правило 2: Клиент должен существовать
    IF NOT EXISTS (SELECT 1 FROM customers WHERE id = NEW.customer_id) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Клиент не найден';
    END IF;
END //
DELIMITER ;
```

#### Валидация

- Попытка вставить некорректные данные возвращает ошибку:
  ```sql
  INSERT INTO orders (customer_id, total) VALUES (9999, 100);
  -- → ERROR: Клиент 9999 не найден
  ```
- Корректные данные проходят без ошибок.
- Проверка на производительность: `EXPLAIN ANALYZE INSERT ...` — триггер добавляет не более 1-2 ms на строку для простых правил.

#### Откат

```sql
-- PostgreSQL
DROP TRIGGER trg_validate_order ON orders;
DROP FUNCTION fn_validate_order_business_rules();

-- MariaDB/MySQL
DROP TRIGGER trg_validate_order;
```

#### Замечания для SRE

- Триггер `BEFORE` — единственное место, где бизнес-правила гарантированно выполняются для всех операций записи. `COPY FROM` вызывает и `BEFORE`, и `AFTER`-триггеры (а также check-ограничения) таблицы-назначения; правила не вызываются. Поэтому массовая загрузка через `COPY` **не** обходит валидацию — но её стоит делать осознанно: триггер на каждой строке умножает время загрузки, а на таблице с включённым RLS `COPY FROM` вообще не поддерживается (используйте `INSERT`).
- Учтите, что триггеры не срабатывают при отключении через `SET session_replication_role = 'replica'` и при загрузке данных в обход триггеров (логическая репликация с `session_replication_role = replica` на подписчике, `pg_dump --disable-triggers`). Если правило критично для целостности, дублируйте его ограничениями или `CHECK`, а не полагайтесь только на триггер.
- Для сложной валидации (например, проверка консистентности между несколькими таблицами) используйте явную блокировку `SELECT ... FOR SHARE` внутри триггера, но учитывайте риск deadlock.
- Недостаток: `BEFORE` триггеры скрывают логику валидации от разработчиков. Документируйте правила в runbook и добавляйте аналогичные проверки на уровне ORM/приложения для fail-fast.
- См. также: [Troubleshooting хранимых объектов](troubleshooting.md) — типичные ошибки валидации.

---

### Сценарий 7: Алерт по пороговому значению (событие + функция)

**Задача:** При достижении критического уровня запасов товара создать запись в таблице уведомлений и оповестить ответственного через `pg_notify` (PostgreSQL) или `INSERT` в очередь (MariaDB).

#### Предварительные требования

- Права `CREATE FUNCTION`, `CREATE EVENT` (MariaDB/MySQL) или суперпользователь для `pg_cron` (PostgreSQL).
- Таблица `stock_alerts` должна быть в отдельной схеме (PostgreSQL) или базе (MariaDB), доступной для приложения-мониторинга.
- В PostgreSQL: приложение-слушатель должно выполнять `LISTEN stock_alert_channel`.

#### PostgreSQL

```sql
-- Функция проверки порога
CREATE OR REPLACE FUNCTION fn_check_stock_threshold()
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_low_stock_count INT;
BEGIN
    SELECT COUNT(*) INTO v_low_stock_count
    FROM products
    WHERE stock_quantity < min_stock_threshold
      AND low_stock_notified = FALSE;

    IF v_low_stock_count > 0 THEN
        INSERT INTO stock_alerts (alert_type, message, created_at)
        VALUES ('low_stock', CONCAT('Товаров ниже порога: ', v_low_stock_count), NOW());

        -- Оповещение для внешнего слушателя
        PERFORM pg_notify('stock_alert_channel', CONCAT('low_stock:', v_low_stock_count));

        -- Помечаем как уведомлённые
        UPDATE products
        SET low_stock_notified = TRUE
        WHERE stock_quantity < min_stock_threshold;
    END IF;
END;
$$;

-- Планировщик: проверка каждый час
SELECT cron.schedule(
    'check-stock-threshold',
    '0 * * * *',
    $$SELECT fn_check_stock_threshold()$$
);
```

#### MariaDB/MySQL

```sql
-- Таблица уведомлений
CREATE TABLE stock_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Функция проверки
-- Валидация: выполняется как PROCEDURE, а не FUNCTION. При включённом бинарном
-- логе CREATE FUNCTION обязан объявить DETERMINISTIC / NO SQL / READS SQL DATA
-- (иначе ERROR 1418), а функция, которая пишет данные, этим условиям не отвечает:
-- пришлось бы объявить DETERMINISTIC заведомо ложно. Дополнительно функция
-- перед выполнением берёт табличные блокировки, тогда как процедура их не берёт.
DELIMITER //
CREATE PROCEDURE proc_check_stock_threshold()
BEGIN
    DECLARE v_low_stock_count INT;

    SELECT COUNT(*) INTO v_low_stock_count
    FROM products
    WHERE stock_quantity < min_stock_threshold
      AND low_stock_notified = FALSE;

    IF v_low_stock_count > 0 THEN
        INSERT INTO stock_alerts (alert_type, message)
        VALUES ('low_stock', CONCAT('Товаров ниже порога: ', v_low_stock_count));

        UPDATE products
        SET low_stock_notified = TRUE
        WHERE stock_quantity < min_stock_threshold;
    END IF;
END //
DELIMITER ;

-- Событие: каждый час
CREATE EVENT evt_check_stock_threshold
ON SCHEDULE EVERY 1 HOUR
STARTS CONCAT(CURDATE(), ' 00:00:00')
ON COMPLETION PRESERVE
ENABLE
DO
    CALL proc_check_stock_threshold();
```

#### Валидация

- Установите `stock_quantity < min_stock_threshold` для тестового товара, дождитесь срабатывания.
- В `stock_alerts` появилась запись с `alert_type = 'low_stock'`.
- В PostgreSQL: внешний слушатель получил уведомление:
  ```sql
  LISTEN stock_alert_channel;
  -- → Asynchronous notification "stock_alert_channel" with payload "low_stock:5" received from server process ...
  ```
- Проверьте, что `low_stock_notified` установлено в `TRUE` для пороговых товаров.

#### Откат

```sql
-- PostgreSQL
SELECT cron.unschedule('check-stock-threshold');
DROP FUNCTION fn_check_stock_threshold();

-- MariaDB/MySQL
DROP EVENT evt_check_stock_threshold;
DROP PROCEDURE proc_check_stock_threshold;
```

#### Замечания для SRE

- `pg_notify` не сохраняет сообщения между перезапусками: если слушатель был offline — уведомление потеряно. Для критичных алертов комбинируйте `pg_notify` с durable записью в `stock_alerts`.
- `pg_notify` работает только при session pooling: в transaction pooling уведомление доставится тому соединению, которое после `COMMIT` окажется в пуле, а не тому клиенту, который его послал. Подробнее — в [Сценарии 2, раздел про `pg_notify`](#уведомление-о-завершении-pg_notify-и-пул-соединений).
- В MariaDB/MySQL нет встроенного механизма `LISTEN/NOTIFY`. Для реального оповещения используйте:
  - `INSERT` в таблицу `stock_alerts` + поллинг со стороны приложения.
  - Внешний агент (Python/Go), читающий `stock_alerts` через триггер на изменение или планировщик.
- Настройте алерт на рост `stock_alerts` без последующего списания — это указывает на проблему с поставками.
- Для production: добавьте в функцию проверку `ROW_COUNT` и логирование в `admin_log` (аналогично Сценарию 4).

---

### Сценарий 8: Идемпотентное задание по расписанию

**Задача:** Задание по расписанию должно безопасно выполняться повторно: после
сбоя на середине, после ретрая или после ручного перезапуска оно не должно
создавать дубликаты. Это самое частое требование к планировщику нагрузки.

**Предварительные требования**

- Отдельная таблица учёта прогонов — это и журнал, и источник истины о том,
  был ли уже обработан диапазон.
- Понимание, что **планировщик не даёт идемпотентности**: `pg_cron` выполняет не
  более одного экземпляра конкретного задания одновременно, а следующий запуск
  ставится в очередь, но повторное применение тех же данных ничто не
  предотвращает. Общий принцип — в [Идемпотентность](../../../Concepts/idempotency.md).

#### PostgreSQL (pg_cron)

```sql
-- Таблица учёта прогонов: уникальность на уровне БД, а не в коде
CREATE TABLE etl_runs (
    run_id      BIGSERIAL PRIMARY KEY,
    batch_date  DATE NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rows_loaded INT NOT NULL DEFAULT 0,
    CONSTRAINT uq_etl_batch UNIQUE (batch_date)
);

-- Тело задания: проверка «уже сделано» и защита от гонки через upsert
CREATE OR REPLACE FUNCTION app.load_daily_batch(p_batch_date DATE)
RETURNS INT AS $$
DECLARE
    v_inserted INT := 0;
BEGIN
    -- Регистрируем попытку. ON CONFLICT DO NOTHING отсекает
    -- параллельный запуск: если строка уже есть, вставка не произойдёт.
    INSERT INTO etl_runs (batch_date, rows_loaded)
    VALUES (p_batch_date, 0)
    ON CONFLICT (batch_date) DO NOTHING;

    IF NOT FOUND THEN
        RAISE NOTICE 'Батч % уже обработан ранее — пропускаем', p_batch_date;
        RETURN 0;
    END IF;

    SELECT count(*) INTO v_inserted
    FROM staging_import s
    WHERE s.batch_date = p_batch_date
      AND s.processed_at IS NULL;

    UPDATE staging_import
       SET processed_at = NOW()
     WHERE batch_date = p_batch_date
       AND processed_at IS NULL;

    UPDATE etl_runs
       SET rows_loaded = v_inserted, started_at = NOW()
     WHERE batch_date = p_batch_date;

    RETURN v_inserted;
END;
$$ LANGUAGE plpgsql;

-- Задание с явной передачей аргумента и ограничением времени
SELECT cron.schedule('load-daily-batch', '30 1 * * *',
                     $$SELECT app.load_daily_batch(current_date)$$);

-- Проверка повторного запуска: результат должен быть 0, а не повторная загрузка
SELECT app.load_daily_batch(current_date);
-- → 0
SELECT app.load_daily_batch(current_date);
-- → 0
```

Ключевой приём — `INSERT ... ON CONFLICT DO NOTHING` **до** начала работы. Он
даёт атомарную проверку: уникальное ограничение делает проверку и вставку одной
операцией, поэтому два параллельных запуска не оба увидят «ещё не
обработано». Проверка `IF NOT EXISTS SELECT ...` перед вставкой дала бы
гонку.

#### MariaDB/MySQL (Event Scheduler)

```sql
CREATE TABLE etl_runs (
    run_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    batch_date  DATE NOT NULL,
    started_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rows_loaded INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_etl_batch (batch_date)
) ENGINE=InnoDB;

DELIMITER //

CREATE PROCEDURE load_daily_batch(IN p_batch_date DATE)
BEGIN
    DECLARE v_inserted INT DEFAULT 0;

    INSERT INTO etl_runs (batch_date, rows_loaded)
    VALUES (p_batch_date, 0)
    ON DUPLICATE KEY UPDATE batch_date = batch_date;
    -- Нет изменённых строк → батч уже обработан
    IF ROW_COUNT() = 0 THEN
        -- MySQL: сигнализировать выход через LEAVE
        -- (в MariaDB допустим RETURN)
        SELECT 'already processed' AS status;
    ELSE
        SELECT count(*) INTO v_inserted
        FROM staging_import
        WHERE batch_date = p_batch_date AND processed_at IS NULL;

        UPDATE staging_import
           SET processed_at = NOW()
         WHERE batch_date = p_batch_date AND processed_at IS NULL;

        UPDATE etl_runs
           SET rows_loaded = v_inserted, started_at = NOW()
         WHERE batch_date = p_batch_date;
    END IF;
END//

DELIMITER ;

CREATE EVENT evt_load_daily_batch
ON SCHEDULE EVERY 1 DAY
STARTS CONCAT(CURDATE() + INTERVAL 1 DAY, ' 01:30:00')
ON COMPLETION PRESERVE
ENABLE
COMMENT 'Идемпотентная загрузка дневного батча'
DO CALL load_daily_batch(CURDATE());
```

Обратите внимание на `ON COMPLETION PRESERVE`: без него одноразовое событие
удалится после выполнения, и в `information_schema.EVENTS` его больше не
будет — отчёт об этом будет выглядеть как «событие потеряно».

#### Валидация

```sql
-- PostgreSQL: прогон зарегистрирован ровно один раз
SELECT batch_date, count(*) FROM etl_runs GROUP BY batch_date HAVING count(*) > 1;
-- → (0 rows) — дублей нет

-- Последние прогоны со статусом
SELECT jobid, runid, status, return_message, start_time
FROM cron.job_run_details
WHERE command LIKE '%load_daily_batch%'
ORDER BY start_time DESC LIMIT 5;
```

```sql
-- MariaDB/MySQL
SELECT batch_date, rows_loaded, started_at FROM etl_runs
ORDER BY batch_date DESC LIMIT 5;
```

Дополнительная проверка идемпотентности: **запустите задание дважды
подряд вручную** и убедитесь, что количество строк в целевой таблице не
изменилось. Это единственный тест, который проверяет свойство, а не
конкретную реализацию.

#### Откат

Откат идемпотентного задания — удаление записи из журнала прогонов, иначе после
отката задание будет считать батч уже обработанным и не сделает работу:

```sql
-- PostgreSQL / MariaDB: снять метку, чтобы задание отработало снова
DELETE FROM etl_runs WHERE batch_date = '2026-10-05';
```

#### Замечания для SRE

- Планировщик даёт очередь, но не защиту от повторного применения: защита
  строится внутри задания. Не рассчитывайте на то, что «задание и так не
  запустится дважды».
- На `cron.job` включён RLS с политикой `username = current_user` — задание,
  созданное одним пользователем, не будет видно и запущено за него в контексте
  другого. Проверяйте `username` в расписании.
- Задания `pg_cron` не выполняются, пока сервер в `hot standby`, и стартуют
  после promotion. Отсутствие запусков на только что переключённом сервере —
  ожидаемое поведение, а не инцидент.
- Записи в `cron.job_run_details` не очищаются автоматически: настройте
  retention отдельной задачей, иначе таблица вырастет неограниченно.

---

## Лучшие практики

1. **Бэкап перед изменением:** перед созданием или заменой триггера/функции/события сделайте дамп объекта (`pg_dump --schema-only` / `mysqldump --routines --triggers --events`). Это ускоряет откат.
2. **Версионируйте в Git:** храните DDL всех хранимых объектов в репозитории. Используйте инструменты миграций (Flyway, Liquibase, Atlas) для деплоя. См. [Database CI/CD](../migrations/database-ci-cd.md).
3. **Тестируйте на копии production:** перед деплоем аудита или валидации запустите процедуру на dev-копии с production-данными, чтобы оценить латентность и объем.
4. **Именуйте единообразно:** `fn_` для функций, `sp_` для процедур, `trg_` для триггеров, `evt_` для событий. Это упрощает отладку и поиск в `information_schema`.
5. **Не используйте триггеры для cross-schema операций без явного списка схем:** в PostgreSQL триггеры по умолчанию не срабатывают для операций из других схем. Если нужно — используйте `SECURITY DEFINER` с осторожностью. См. [Безопасность хранимых объектов](security.md).
6. **Документируйте baseline:** для каждого сценария запишите ожидаемое время выполнения и объём обрабатываемых данных в runbook. См. [Мониторинг хранимых объектов](monitoring.md).
7. **Планируйте откат до запуска:** для каждого сценария должен быть проверенный скрипт отката (drop trigger/function/event + restore data). Тестируйте откат на staging.
8. **Настраивайте on-call runbook:** при инциденте с хранимым объектом первый шаг — проверка блокировок, второй — проверка таймаутов, третий — принудительная остановка сессии. См. [Troubleshooting хранимых объектов](troubleshooting.md).

---

## Дополнительная информация

### См. также

- **[Безопасность хранимых объектов](security.md)** — модель привилегий, `SECURITY DEFINER`/`DEFINER`, динамический SQL.
- **[Мониторинг хранимых объектов](monitoring.md)** — `pg_stat_user_functions`, `pg_stat_statements`, Performance Schema, baseline.
- **[Troubleshooting хранимых объектов](troubleshooting.md)** — типичные ошибки, рекурсия, блокировки, ограничения по СУБД, on-call runbook.
- **[Управление хранимыми объектами в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)** — Event Scheduler, отладка, SIGNAL/RESIGNAL.
- **[Отладка объектов в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md)** — техники профилирования и поиска ошибок.
- **[Database CI/CD](../migrations/database-ci-cd.md)** — автоматизация деплоя хранимых объектов, drift detection, GitOps.
