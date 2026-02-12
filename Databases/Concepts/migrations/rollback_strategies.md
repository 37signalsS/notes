# Rollback стратегии для миграций

## Стратегия 1: Down миграции

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

## Стратегия 2: Backup + Restore

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

## Стратегия 3: Feature Flags + Rollback

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
