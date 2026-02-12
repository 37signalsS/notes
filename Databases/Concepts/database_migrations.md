# Миграции баз данных

## Определения

**Миграция базы данных** — это управляемый процесс внесения изменений в схему базы данных (добавление/изменение таблиц, индексов, ограничений) с сохранением существующих данных и обеспечением целостности.

**Rollback** — процесс отката миграции к предыдущему состоянию схемы при обнаружении проблем.

## Почему нужны миграции

```
Проблема без миграций:

Разработчик 1                    Разработчик 2
     │                                │
     ▼                                ▼
ALTER TABLE users              ALTER TABLE users
ADD COLUMN phone;              ADD COLUMN address;
     │                                │
     └────────────────┬───────────────┘
                      ▼
               Конфликт при merge!
               Кто-то теряет свои изменения
               
Проблемы:
- Несогласованность схем между dev/prod
- Потеря данных при ручных ALTER
- Невоспроизводимые изменения
- Сложность rollback
```

## Типы миграций

### 1. Schema Migrations (Схемные)

```sql
-- Создание таблицы
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Добавление колонки
ALTER TABLE users ADD COLUMN phone VARCHAR(20);

-- Создание индекса
CREATE INDEX idx_users_email ON users(email);
```

### 2. Data Migrations (Данные)

```sql
-- Миграция существующих данных
UPDATE users 
SET full_name = first_name || ' ' || last_name
WHERE full_name IS NULL;

-- Денормализация
INSERT INTO user_stats (user_id, order_count)
SELECT user_id, COUNT(*) 
FROM orders 
GROUP BY user_id;
```

### 3. Seed Migrations (Начальные данные)

```sql
-- Заполнение справочников
INSERT INTO countries (code, name) VALUES 
('US', 'United States'),
('UK', 'United Kingdom'),
('DE', 'Germany');
```

## Инструменты миграций

### Сравнение инструментов

| Инструмент | Язык | Поддержка | Особенности |
|------------|------|-----------|-------------|
| **Flyway** | Java | Все SQL БД | SQL-first, versioning |
| **Liquibase** | Java | Все SQL БД | XML/YAML/JSON/SQL |
| **Alembic** | Python | SQLAlchemy | Автогенерация |
| **Django Migrations** | Python | Django ORM | Интегрировано |
| **Prisma Migrate** | TypeScript | PostgreSQL, MySQL | Declarative |
| **golang-migrate** | Go | Множество БД | CLI-first |
| **dbmate** | Go | Множество БД | Простота |
| **Atlas** | Go | Множество БД | Modern, Terraform-like |

## Практики миграций

### 1. Именование и версионирование

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

### 2. Идемпотентность

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

### 3. Транзакционность

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

## Rollback стратегии

### Стратегия 1: Down миграции

```sql
-- V2__add_phone_column.sql
ALTER TABLE users ADD COLUMN phone VARCHAR(20);

-- U2__add_phone_column.sql (Rollback)
ALTER TABLE users DROP COLUMN phone;
```

**Проблемы:**
- Потеря данных при drop column
- Сложность при data migrations
- Не всегда возможно (DROP TABLE)

### Стратегия 2: Backup + Restore

```bash
#!/bin/bash
# backup_before_migration.sh

BACKUP_NAME="pre_migration_$(date +%Y%m%d_%H%M%S).sql"
pg_dump -h $DB_HOST -U $DB_USER $DB_NAME > $BACKUP_NAME

# Выполняем миграцию
flyway migrate

# Если ошибка — восстанавливаем
if [ $? -ne 0 ]; then
    psql -h $DB_HOST -U $DB_USER $DB_NAME < $BACKUP_NAME
    echo "Rollback completed"
    exit 1
fi
```

### Стратегия 3: Feature Flags + Rollback

```python
# Постепенное внедрение с возможностью отката
if feature_flags.is_enabled('new_user_schema'):
    # Новая схема
    user = UserV2.query.get(user_id)
else:
    # Старая схема
    user = User.query.get(user_id)

# При проблеме: отключаем toggle
# Никаких изменений в БД не требуется!
```

## Backward-compatible миграции

### Принцип Expand-Contract

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

### Пример Expand-Contract

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

## CI/CD интеграция

### Пайплайн миграций

```yaml
# .gitlab-ci.yml
stages:
  - migrate
  - test
  - deploy

db_migrate:
  stage: migrate
  image: flyway/flyway:latest
  script:
    - flyway -url=$DB_URL -user=$DB_USER -password=$DB_PASSWORD migrate
  only:
    - main
  environment:
    name: production
    url: https://api.production.com

# Проверка перед merge
migrate_dry_run:
  stage: test
  image: flyway/flyway:latest
  script:
    - flyway -url=$STAGING_DB_URL info
    - flyway -url=$STAGING_DB_URL validate
  only:
    - merge_requests
```

### Проверка backward compatibility

```bash
#!/bin/bash
# check_migration_compatibility.sh

# 1. Проверяем, что нет DROP COLUMN
grep -r "DROP COLUMN" db/migrations/ && {
    echo "ERROR: DROP COLUMN detected. Use Expand-Contract pattern."
    exit 1
}

# 2. Проверяем, что ALTER TABLE не удаляет данные
grep -ri "ALTER TABLE.*DROP" db/migrations/ && {
    echo "ERROR: Destructive ALTER detected."
    exit 1
}

# 3. Проверяем, что новые колонки nullable или имеют DEFAULT
echo "Migration compatibility check passed!"
```

## Типичные сценарии

### Сценарий 1: Zero-downtime deployment

```sql
-- Миграция 1: Добавление nullable колонки
ALTER TABLE orders ADD COLUMN tracking_number VARCHAR(100);
-- ✅ Быстро, не блокирует

-- Деплой 1: Код учитывает nullable
# if order.tracking_number:
#     show_tracking(order.tracking_number)

-- Миграция 2: Добавление default (опционально)
ALTER TABLE orders ALTER COLUMN tracking_number SET DEFAULT 'PENDING';

-- Деплой 2: Код предполагает not-null
# show_tracking(order.tracking_number)  # Всегда есть значение

-- Миграция 3: NOT NULL constraint (если нужно)
UPDATE orders SET tracking_number = 'PENDING' WHERE tracking_number IS NULL;
ALTER TABLE orders ALTER COLUMN tracking_number SET NOT NULL;
```

### Сценарий 2: Сложная миграция большой таблицы

```python
# batch_migration.py
# Миграция по батчам для избежания блокировок

BATCH_SIZE = 1000
last_id = 0

while True:
    with db.transaction():
        rows = db.execute(f"""
            SELECT id FROM large_table 
            WHERE id > {last_id} 
            ORDER BY id 
            LIMIT {BATCH_SIZE}
            FOR UPDATE SKIP LOCKED
        """)
        
        if not rows:
            break
            
        for row in rows:
            migrate_row(row.id)
            last_id = row.id
    
    # Пауза между батчами
    time.sleep(0.1)
```

### Сценарий 3: Откат проблемной миграции

```bash
# 1. Остановить деплой
kubectl rollout pause deployment/myapp

# 2. Проверить статус миграций
flyway info

# 3. Откат (если поддерживается)
flyway undo  # Только для версионированных миграций

# 4. Или восстановление из бэкапа
pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME backup.sql

# 5. Откат кода
git revert HEAD
kubectl rollout resume deployment/myapp
```

## Мониторинг миграций

### Метрики

```python
from datadog import statsd
import time

def run_migration(migration_file):
    start_time = time.time()
    
    try:
        execute_migration(migration_file)
        
        statsd.increment('db.migration.success', 
                        tags=[f'file:{migration_file}'])
        statsd.histogram('db.migration.duration',
                        time.time() - start_time,
                        tags=[f'file:{migration_file}'])
        
    except Exception as e:
        statsd.increment('db.migration.failure',
                        tags=[f'file:{migration_file}', f'error:{type(e).__name__}'])
        raise
```

### Алерты

```yaml
# Alerting rules
- alert: LongRunningMigration
  expr: db_migration_duration_seconds > 300
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Migration {{ $labels.file }} is taking too long"

- alert: FailedMigration
  expr: increase(db_migration_failure_total[5m]) > 0
  labels:
    severity: critical
  annotations:
    summary: "Database migration failed"
```

## Best Practices

1. **Всегда тестируйте на staging**
2. **Используйте transactions** где возможно
3. **Делайте бэкапы перед миграциями**
4. **Следуйте Expand-Contract** для breaking changes
5. **Документируйте миграции**
6. **Мониторьте время выполнения**
7. **Используйте CONCURRENTLY** для индексов в PostgreSQL
8. **Избегайте data migrations в транзакциях** для больших таблиц
9. **Тестируйте rollback** перед production
10. **Используйте feature flags** для контроля новой функциональности

## Дополнительная информация

- [Flyway Documentation](https://documentation.red-gate.com/flyway)
- [Liquibase Documentation](https://docs.liquibase.com/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Strong Migrations (Rails)](https://github.com/ankane/strong_migrations)
- [PostgreSQL Migration Guide](https://www.postgresql.org/docs/current/sql-altertable.html)
