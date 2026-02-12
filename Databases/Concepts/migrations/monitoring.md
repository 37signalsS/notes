# Мониторинг миграций

## Метрики

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

## Алерты

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
