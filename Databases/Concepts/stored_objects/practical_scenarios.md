# Практические сценарии: хранимые объекты

## Сценарий 1: Аудит изменений данных (триггер)

**Задача:** Автоматически логировать все изменения в таблице `employees` (кто, когда, что изменил).

### PostgreSQL

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

### MariaDB/MySQL

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

---

## Сценарий 2: Пакетная обработка (процедура)

**Задача:** Безопасно обработать миллионы записей небольшими порциями, чтобы не перегружать БД и не блокировать другие сессии.

### PostgreSQL

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

### MariaDB/MySQL

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

---

## Сценарий 3: Вычисляемые данные (функция)

**Задача:** Функция для расчёта стоимости доставки на основе веса, расстояния и уровня клиента.

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

### Табличная функция (PostgreSQL)

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

### Функция вычисления возраста (MariaDB)

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

---

## Сценарий 4: Ротация логов (событие)

**Задача:** Ежедневно удалять записи старше 90 дней из таблицы логов.

### MariaDB/MySQL

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

### PostgreSQL (pg_cron)

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

---

## Сценарий 5: Синхронизация агрегатов (триггер)

**Задача:** При добавлении/удалении заказа автоматически обновлять агрегированную статистику клиента.

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
            total_spent = total_spent - OLD.total
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
