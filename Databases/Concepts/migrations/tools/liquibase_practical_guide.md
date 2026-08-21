# Liquibase: Практическое руководство по эксплуатации

## Определения

*   **Changelog (Журнал изменений):** Корневой файл (XML, YAML, JSON или SQL), содержащий список всех изменений БД.
*   **Changeset (Набор изменений):** Атомарная единица изменений, идентифицируемая парой `id` и `author`.
*   **DatabaseChangeLog (Таблица истории):** Системная таблица `DATABASECHANGELOG`, где хранится история примененных ченджсетов.
*   **Contexts (Контексты):** Механизм фильтрации миграций по окружениям (например, `test`, `prod`).
*   **Rollback (Откат):** Процесс отмены изменений, описанный внутри ченджсета или вычисляемый автоматически для стандартных команд.

## Базовые конфигурации

### 1. Конфигурация через `liquibase.properties`
Рекомендуется для CLI и Docker.

```properties
changeLogFile=db/changelog/db.changelog-master.yaml
url=jdbc:postgresql://localhost:5432/mydb
username=liquibase_user
password=${DB_PASSWORD}
driver=org.postgresql.Driver
# Путь к драйверу (если не в classpath)
classpath=drivers/postgresql-42.6.0.jar
```

### 2. Пример Changeset в YAML (с ручным откатом)
```yaml
databaseChangeLog:
  - changeSet:
      id: 1
      author: devops_engineer
      changes:
        - addColumn:
            tableName: users
            columns:
              - column:
                  name: middle_name
                  type: varchar(50)
      rollback:
        - dropColumn:
            tableName: users
            columnName: middle_name
```

---

## CI/CD Пайплайны

### 1. GitLab CI (через Docker)
Использование официального образа `liquibase/liquibase`.

```yaml
migrate_db:
  stage: deploy
  image: 
    name: liquibase/liquibase:4.24.0
    entrypoint: [""]
  script:
    - /liquibase/liquibase \
        --url="jdbc:postgresql://${DB_HOST}:5432/${DB_NAME}" \
        --changelog-file="db/changelog/db.changelog-master.yaml" \
        --username="${DB_USER}" \
        --password="${DB_PASSWORD}" \
        update
  only:
    - tags
```

### 2. GitHub Actions (с генерацией SQL-отчета)
SRE Best Practice: генерация SQL перед применением для аудита.

```yaml
jobs:
  db-update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: liquibase-action/update@v4.24.0
        with:
          changelogFile: "db/changelog/db.changelog-master.yaml"
          url: ${{ secrets.DB_URL }}
          username: ${{ secrets.DB_USER }}
          password: ${{ secrets.DB_PASSWORD }}
      - name: Generate Rollback SQL
        run: |
          docker run --rm -v $(pwd):/liquibase/changelog liquibase/liquibase \
            --changelog-file=/liquibase/changelog/db.changelog-master.yaml \
            future-rollback-sql > rollback_preview.sql
```

---

## Сложные откаты и стратегии восстановления

### 1. Использование тега `<rollback>`
Для сложных операций (например, миграция данных через `sql` тег) Liquibase не может вычислить откат автоматически.
*   **Пример:**
    ```yaml
    - changeSet:
        id: transfer-data
        author: dba
        changes:
          - sql:
              sql: "UPDATE accounts SET balance = balance - 100 WHERE id = 1"
        rollback:
          - sql:
              sql: "UPDATE accounts SET balance = balance + 100 WHERE id = 1"
    ```

### 2. Откат к тегу (Tag Rollback)
SRE паттерн: тегирование состояния БД перед каждым релизом.
1. В начале пайплайна: `liquibase tag --tag release-2.1`.
2. Если деплой провален: `liquibase rollback --tag release-2.1`.

### 3. Откат по количеству (Rollback Count)
`liquibase rollback-count 3` — отменяет последние 3 примененных ченджсета. Используйте с осторожностью, так как это может привести к потере данных, добавленных в промежутке.

---

## Рекомендации SRE

*   **Contexts и Labels:** Используйте контексты для специфических задач. Например, `context: test` для заполнения базы тестовыми данными, которые никогда не попадут на `prod`.
*   **Preconditions:** Проверяйте состояние БД перед выполнением миграции.
    ```yaml
    - changeSet:
        id: add-index-safely
        preConditions:
          - onFail: MARK_RAN
          - not:
              indexExists:
                indexName: idx_user_email
    ```
*   **Diff-задачи:** Используйте `liquibase diff` для поиска расхождений между Development и Production базами. Это лучший способ обнаружить "дрейф схемы".
*   **Fail-Fast:** Настраивайте `liquibase validate` в CI для раннего обнаружения ошибок в синтаксисе ченджлогов.

## См. также
- **[Database CI/CD](../database-ci-cd.md)** — общие принципы автоматизации.
- **[Стратегии отката (Rollback)](../rollback_strategies.md)** — теоретическая база.
- **[Flyway: Практическое руководство](./flyway_practical_guide.md)** — альтернативный инструмент.
