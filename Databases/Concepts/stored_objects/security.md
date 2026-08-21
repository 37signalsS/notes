# Безопасность хранимых объектов

## Модель привилегий

### PostgreSQL

| Привилегия | Объект | Описание |
|---|---|---|
| `EXECUTE` | Функция / Процедура | Право на вызов хранимого объекта |
| `USAGE` | Схема | Право на доступ к объектам в схеме (включая триггерные функции) |
| `CREATE` | Схема | Право на создание объектов в схеме |
| `TRIGGER` | Таблица | Право на создание триггера на таблице |

**Принцип наименьших привилегий:** Приложение должно работать от имени роли с минимальными правами. Прямой доступ к таблицам запрещён, доступ — только через хранимые объекты.

```sql
-- Создание роли для приложения
CREATE ROLE app_role;

-- Запрет прямого доступа к таблицам
REVOKE ALL ON orders FROM app_role;
REVOKE ALL ON customers FROM app_role;

-- Разрешение только через хранимые объекты
GRANT EXECUTE ON PROCEDURE update_order_status TO app_role;
GRANT EXECUTE ON FUNCTION get_order_summary TO app_role;

-- Приложение работает от имени app_role и не может модифицировать данные напрямую
```

**Security Definer vs Security Invoker:**

- `SECURITY DEFINER` — функция выполняется с привилегиями **владельца** функции (того, кто её создал). Опасно, если владелец — суперпользователь.
- `SECURITY INVOKER` (по умолчанию) — функция выполняется с привилегиями **вызывающего** пользователя. Безопаснее.

```sql
-- Опасно: функция выполняется от имениpostgres
CREATE FUNCTION drop_temp_table()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER  -- ← владелец = postgres, выполняется с его привилегиями
AS $$ DROP TABLE IF EXISTS temp_data; $$;

-- Безопасно: функция выполняется от имени вызывающего
CREATE FUNCTION get_order_total(p_id INT)
RETURNS NUMERIC
LANGUAGE sql
SECURITY INVOKER  -- ← привилегии вызывающего пользователя
AS $$ SELECT total FROM orders WHERE id = p_id; $$;
```

### MariaDB/MySQL

MariaDB/MySQL используют модель `Definer` / `Invoker` для хранимых объектов:

- **DEFINER:** Объект выполняется с привилегиями того пользователя, который его создал (definer). Это опасно, если definer — `root`.
- **INVOKER:** Объект выполняется с привилегиями того пользователя, который его вызывает. Безопаснее.

```sql
-- Создание пользователя с минимальными привилегиями
CREATE USER 'app_user'@'%' IDENTIFIED BY 'secure_password';

-- Запрет прямого доступа
REVOKE ALL PRIVILEGES ON mydb.* FROM 'app_user'@'%';

-- Разрешение только на выполнение процедур
GRANT EXECUTE ON PROCEDURE mydb.update_order_status TO 'app_user'@'%';
GRANT EXECUTE ON FUNCTION mydb.calculate_total TO 'app_user'@'%';

FLUSH PRIVILEGES;
```

**Проверка security_type:**

```sql
SELECT routine_name, security_type
FROM information_schema.routines
WHERE routine_schema = 'mydb';
-- → routine_name       | security_type
-- → -------------------+--------------
-- → update_order_status| DEFINER      -- опасно, если definer = root
-- → calculate_total    | INVOKER      -- безопасно
```

**Рекомендации:**
- Всегда создавайте хранимые объекты от имени специализированных пользователей, а не `root`.
- Используйте `INVOKER` там, где это возможно.
- Если необходим `DEFINER`, убедитесь, что definer-пользователь имеет минимально необходимые привилегии.
- Периодически аудитируйте `DEFINER`-объекты через `information_schema.routines`.

---

## Динамический SQL и безопасность

Динамический SQL внутри хранимых объектов — источник SQL-инъекций, если входные параметры не экранированы.

**PostgreSQL (PL/pgSQL):**

```sql
-- ОПАСНО: SQL-инъекция через параметр
CREATE OR REPLACE FUNCTION unsafe_search(p_table TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE format('SELECT id, name FROM %I', p_table);
    -- format('%I') экранирует имя таблицы — безопасно
END;
$$;

-- ОПАСНО: прямая подстановка
CREATE OR REPLACE FUNCTION unsafe_query(p_name TEXT)
RETURNS TABLE(id INT)
LANGUAGE plpgsql
AS $$
BEGIN
    -- НИКОГДА так не делайте:
    RETURN QUERY EXECUTE 'SELECT id FROM users WHERE name = ''' || p_name || '''';
    -- → SQL-инъекция: p_name = "'; DROP TABLE users; --"
END;
$$;

-- Безопасно: параметризованный запрос
CREATE OR REPLACE FUNCTION safe_search(p_name TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE
        'SELECT id, name FROM users WHERE name = $1'
        USING p_name;
    -- Параметр передаётся через USING — экранирование автоматическое
END;
$$;
```

**MariaDB/MySQL:**

```sql
-- Безопасно: prepared statement с параметрами
DELIMITER //
CREATE PROCEDURE safe_search(IN p_name VARCHAR(100))
BEGIN
    SET @sql = 'SELECT id, name FROM users WHERE name = ?';
    SET @p = p_name;
    PREPARE stmt FROM @sql;
    EXECUTE stmt USING @p;
    DEALLOCATE PREPARE stmt;
END //
DELIMITER ;
```

---

## Рекомендации по безопасности

1. **Принцип наименьших привилегий:** Каждый хранимый объект должен выполнять только необходимые операции. Не используйте `SECURITY DEFINER` без крайней необходимости.
2. **Аудит definer-объектов:** Периодически проверяйте, какие объекты выполняются от имени суперпользователей.
3. **Экранирование в динамическом SQL:** Всегда используйте `format('%I')` (PostgreSQL) или prepared statements (MariaDB) для параметров.
4. **Не храните секреты в объектах:** Пароли подключений, API-ключи и т.д. не должны быть в теле функций/процедур. Используйте внешние vault-сервисы.
5. **GRANT EXECUTE через роли:** Не выдавайте `EXECUTE` напрямую пользователям — группируйте через роли.
