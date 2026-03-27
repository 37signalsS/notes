# PostgreSQL Schema Migrations

## Definitions

* **Миграция схемы:** Упорядоченный, версионируемый процесс изменения структуры базы данных (например, добавление таблиц или колонок).
* **Откат миграции (Rollback):** Процесс отмены примененных изменений для возврата схемы к предыдущему состоянию.

## Basic Concepts

Общие концепции управления миграциями (императивный vs декларативный подход, стратегии отката, expand-contract) описаны в **[Миграции баз данных: Основы](../../../Concepts/migrations/migration_basics.md)**.

### PostgreSQL-Specific Considerations

* **Транзакционность DDL:** PostgreSQL поддерживает транзакции для DDL-операций. Миграции можно оборачивать в `BEGIN ... COMMIT`, что обеспечивает атомарность изменений.
* **Блокировки при миграциях:** DDL-операции (например, `ALTER TABLE`) могут блокировать таблицу на время выполнения. Для больших таблиц это критично.
* **Расширения (Extensions):** PostgreSQL поддерживает расширения (`CREATE EXTENSION`), которые также требуют версионирования и миграции.

### Safe Rollback Strategies

1. **Reversible Migrations:** Для каждой миграции (`up`) пишется обратная (`down`). Подробно в **[Rollback Strategies](../../../Concepts/migrations/rollback_strategies.md)**.

2. **Expand-Migrate-Contract:** Стратегия для сложных изменений в production. Подробно в **[Expand-Contract Pattern](../../../Concepts/migrations/expand_contract.md)**.

3. **Snapshots и PITR:**
    * **Volume Snapshots:** Создание снимка диска (PVC) перед миграцией в тестовой среде.
    * **Point-in-Time Recovery (PITR):** Восстановление базы на момент времени до начала миграции с помощью [архивирования WAL-журналов](./backup_and_recovery.md).

## Practical Scenarios

### Migration Tools for PostgreSQL

| Инструмент | Тип | Особенности |
| :--- | :--- | :--- |
| **Flyway** | Императивный | Популярен в Java-экосистеме, SQL-скрипты |
| **Liquibase** | Императивный | Поддерживает SQL, XML, YAML, JSON |
| **Atlas** | Декларативный/Императивный | Современный, Schema-as-Code, GitOps |
| **Bytebase** | Декларативный | Веб-интерфейс, "Git для БД" |
| **SchemaHero** | Декларативный | Kubernetes-оператор |

### Atlas Workflow for PostgreSQL

**Atlas** — современный инструмент для автоматизации управления миграциями с поддержкой PostgreSQL.

#### Declarative Mode (Schema-as-Code)

1. **Инспекция схемы:**

    ```bash
    # Сохранить схему текущей базы в файл schema.hcl
    atlas schema inspect -u "postgres://user:pass@host:5432/dbname?sslmode=disable" > schema.hcl
    ```

2. **Применение изменений:**

    ```bash
    atlas schema apply -u "postgres://..." --to "file://schema.hcl" --dev-url "docker://postgres/15"
    ```

#### Versioned Mode (Migration Files)

1. **Генерация файла миграции:**

    ```bash
    # Создать SQL-файл для новой миграции
    atlas migrate diff add_title_column --dir "file://migrations" --dev-url "docker://postgres/15" --to "file://schema.hcl"
    ```

2. **Применение миграции:**

    ```bash
    atlas migrate apply -u "postgres://..." --dir "file://migrations"
    ```

3. **Автоматический откат:**

    ```bash
    # Откатить последнюю примененную миграцию
    atlas migrate apply -u "postgres://..." --dir "file://migrations" --revert 1
    ```

#### Kubernetes Operator

Atlas предоставляет оператор для Kubernetes, реализующий GitOps-подход: схема БД (`schema.hcl`) хранится в Git, оператор автоматически применяет изменения при обновлении Custom Resource `AtlasSchema`.

### CI/CD Integration

Инструменты миграции интегрируются в CI/CD пайплайны:

1. **CI (на Pull Request):** Автоматическая проверка (`--dry-run`) и генерация миграции.
2. **CD (при мерже в main):** Применение миграций к `staging` и `production`.

Подробнее в **[CI/CD Integration](../../../Concepts/migrations/cicd_integration.md)**.

### PostgreSQL-Specific Migration Scenarios

* **Миграции с `pg_partman`:** Партиционирование требует особых миграций для создания новых партиций.
* **Миграции расширений:** `CREATE EXTENSION IF NOT EXISTS` с указанием версии.
* **Конкурентное создание индексов:** `CREATE INDEX CONCURRENTLY` для избежания блокировок.

## Additional Information

* **Резервное копирование:** PITR и архивирование WAL для восстановления перед миграцией — **[Backup and Recovery](./backup_and_recovery.md)**.
* **Масштабирование:** Переход от партиционирования к шардированию — **[Scaling PostgreSQL](./scaling.md)**.
* **Мониторинг миграций:** Метрики и алерты — **[Migration Monitoring](../../../Concepts/migrations/monitoring.md)**.
* **Лучшие практики:** Именование, идемпотентность — **[Migration Practices](../../../Concepts/migrations/migration_practices.md)**.
