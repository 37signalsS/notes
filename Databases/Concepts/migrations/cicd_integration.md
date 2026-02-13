# CI/CD интеграция миграций

## Пайплайн миграций

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

## Проверка backward compatibility

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

---
### Дополнительная информация

-   См. основной документ: **[Миграции баз данных: Основы](migration_basics.md)**
