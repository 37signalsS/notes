# Практики миграций баз данных

## 1. Именование и версионирование

```
❌ Плохо:
- add_column.sql
- fix_users.sql
- update_db.sql

✅ Хорошо:
Flyway:   V1__create_users_table.sql
          V2__add_users_phone_column.sql
          V3__create_orders_table.sql

Liquibase: 20240101120000_create_users_table.xml
           20240102150000_add_user_phone.yaml
           
Timestamp-based: 20240101120000_create_users.sql
```

## 2. Идемпотентность

```sql
-- ❌ Плохо: упадет при повторном запуске
CREATE TABLE users (id SERIAL PRIMARY KEY);

-- ✅ Хорошо: можно запускать многократно
CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY);

-- Или с проверкой
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables 
                   WHERE tablename = 'users') THEN
        CREATE TABLE users (id SERIAL PRIMARY KEY);
    END IF;
END $$;
```

## 3. Транзакционность

```sql
-- ✅ Все или ничего
BEGIN;

ALTER TABLE users ADD COLUMN phone VARCHAR(20);
CREATE INDEX CONCURRENTLY idx_users_phone ON users(phone);
UPDATE users SET phone = 'N/A' WHERE phone IS NULL;

COMMIT;

-- В PostgreSQL некоторые операции не могут быть в транзакции:
-- CREATE INDEX CONCURRENTLY, VACUUM, ALTER SYSTEM
```

---
### Дополнительная информация

-   См. основной документ: **[Миграции баз данных: Основы](migration_basics.md)**
