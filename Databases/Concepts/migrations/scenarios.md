# Типичные сценарии миграций

## Сценарий 1: Zero-downtime deployment

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

## Сценарий 2: Сложная миграция большой таблицы

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

## Сценарий 3: Откат проблемной миграции

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

---
### Дополнительная информация

-   См. основной документ: **[Миграции баз данных: Основы](migration_basics.md)**
