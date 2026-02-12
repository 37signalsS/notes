# Backward-compatible миграции

## Принцип Expand-Contract

```
Фаза 1: EXPAND (Добавление)
┌────────────────────────────────────────────────────────────┐
│  Старая схема                    Новая схема               │
│                                                            │
│  users                     ┌──────────► users              │
│  ├── id                    │            ├── id             │
│  ├── name                  │            ├── name           │
│  └── email                 │            ├── email          │
│                            │            ├── first_name (new)│
│                            │            └── last_name (new) │
│                            │                              │
│                            │  Код пишет в old (name)      │
│                            │  Триггеры синхронизируют      │
└────────────────────────────────────────────────────────────┘

Фаза 2: MIGRATE (Миграция данных)
┌────────────────────────────────────────────────────────────┐
│  Обновление всех записей:                                  │
│  UPDATE users SET                                          │
│    first_name = SPLIT_PART(name, ' ', 1),                  │
│    last_name = SPLIT_PART(name, ' ', 2);                   │
└────────────────────────────────────────────────────────────┘

Фаза 3: CONTRACT (Удаление)
┌────────────────────────────────────────────────────────────┐
│  Только новая схема                                        │
│                                                            │
│  users                                                     │
│  ├── id                                                    │
│  ├── first_name                                            │
│  ├── last_name                                             │
│  └── email                                                 │
│                                                            │
│  Удаляем name и триггеры                                   │
└────────────────────────────────────────────────────────────┘
```

## Пример Expand-Contract

```sql
-- Фаза 1: Expand
-- Добавляем новые колонки
ALTER TABLE users ADD COLUMN first_name VARCHAR(100);
ALTER TABLE users ADD COLUMN last_name VARCHAR(100);

-- Создаем триггер для синхронизации
CREATE OR REPLACE FUNCTION sync_name()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.first_name IS NOT NULL OR NEW.last_name IS NOT NULL THEN
        NEW.name = NEW.first_name || ' ' || NEW.last_name;
    ELSIF NEW.name IS NOT NULL THEN
        NEW.first_name = SPLIT_PART(NEW.name, ' ', 1);
        NEW.last_name = SPLIT_PART(NEW.name, ' ', 2);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_name_trigger
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION sync_name();

-- Фаза 2: Миграция (выполняется постепенно)
UPDATE users 
SET first_name = SPLIT_PART(name, ' ', 1),
    last_name = SPLIT_PART(name, ' ', 2)
WHERE first_name IS NULL;

-- Фаза 3: Contract (после того как все код переключен)
DROP TRIGGER sync_name_trigger ON users;
DROP FUNCTION sync_name();
ALTER TABLE users DROP COLUMN name;
```
