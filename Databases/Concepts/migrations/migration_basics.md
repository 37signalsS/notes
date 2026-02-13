# Миграции баз данных: Основы

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

---

## Дополнительная информация

Изучив основы, вы можете углубиться в специфические темы:

-   **[Лучшие практики](migration_practices.md):** Именование, идемпотентность и транзакции.
-   **[Стратегии отката (Rollback)](rollback_strategies.md):** Как безопасно отменять изменения.
-   **[Обратно-совместимые миграции (Expand-Contract)](expand_contract.md):** Внесение изменений без простоя.
-   **[Типовые сценарии](scenarios.md):** Примеры для zero-downtime деплоя и работы с большими таблицами.
-   **[Интеграция с CI/CD](cicd_integration.md):** Автоматизация и проверка миграций.
-   **[Мониторинг](monitoring.md):** Метрики и алерты для процесса миграции.
