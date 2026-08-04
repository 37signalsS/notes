# Управление ролями и правами доступа в PostgreSQL

## Концепция ролей
В современных версиях PostgreSQL понятия «пользователь» и «группа» объединены в одну сущность — **Роль**. Разница между ними лишь в настройках:
*   **Пользователь:** Роль с атрибутом `LOGIN`, позволяющим подключаться к БД.
*   **Группа:** Роль без атрибута `LOGIN` (по умолчанию `NOLOGIN`), предназначенная для объединения прав и их наследования пользователями.

По умолчанию при установке создается системный пользователь и роль `postgres`.

## Работа с системной ролью postgres

### Вход в консоль управления
Подробные способы подключения и конфигурации клиента описаны в разделе **[Основы работы в psql](./console_basics.md)**.

**Прямой вход через sudo:**
```bash
sudo -u postgres psql
```

**Переключение на системного пользователя:**
```bash
sudo -i -u postgres
psql
```

## Создание новых ролей

### Создание через SQL
SQL-команды `CREATE ROLE` и `CREATE USER` практически идентичны, за исключением значения параметра `LOGIN` по умолчанию.

```sql
-- Создание пользователя с расширенными атрибутами
CREATE USER app_user 
WITH PASSWORD 'secure_pass' 
VALID UNTIL '2026-12-31'
CONNECTION LIMIT 50        -- Ограничение кол-ва одновременных сессий
BYPASSRLS;                 -- Обход политик Row-Level Security (только для сервисных ролей)

-- Атрибуты прав на уровне кластера (использовать с осторожностью):
-- SUPERUSER | CREATEDB | CREATEROLE | REPLICATION

-- Создание роли без права входа (групповая роль)
CREATE ROLE read_only_group NOLOGIN;
```

### Предопределенные системные роли (PG 10+)
PostgreSQL предоставляет набор ролей для делегирования прав без выдачи статуса `SUPERUSER`:

| Роль | Назначение |
| :--- | :--- |
| `pg_monitor` | Чтение всей статистики, настроек и статусов (идеально для Prometheus/Zabbix). |
| `pg_read_all_data` | (PG 14+) Глобальное право `SELECT` на все таблицы и представления. |
| `pg_write_all_data` | (PG 14+) Глобальное право `INSERT`, `UPDATE`, `DELETE`. |
| `pg_read_all_settings` | Чтение всех конфигурационных параметров, даже защищенных. |
| `pg_signal_backend` | Право на завершение (`kill`) чужих запросов и сессий. |

**Пример выдачи:**
```sql
GRANT pg_monitor TO monitoring_user;
```

### Создание через системную утилиту createuser
Утилита является оберткой над `CREATE ROLE`.
```bash
# Создать пользователя с запросом пароля
sudo -u postgres createuser app_user -P

# Создать пользователя и сразу добавить в группу
sudo -u postgres createuser app_user -P -g read_only_group

# Интерактивный режим (задает вопросы о правах)
sudo -u postgres createuser --interactive
```

## Создание базы данных
По умолчанию роль пытается подключиться к БД с тем же именем.
```bash
sudo -u postgres createdb mydb
```

## Управление правами доступа (GRANT / REVOKE)

### Иерархия прав
В PostgreSQL права выдаются последовательно сверху вниз: `DATABASE` → `SCHEMA` → `TABLE` (или другой объект).

```sql
-- 1. Доступ к базе данных
GRANT CONNECT ON DATABASE mydb TO app_user;

-- 2. Доступ к схеме
-- USAGE позволяет видеть объекты, CREATE позволяет создавать новые
GRANT USAGE, CREATE ON SCHEMA public TO app_user;

-- 3. Доступ к таблицам
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO read_only_group;
```

### Права по умолчанию (Default Privileges)
Частая проблема: права выданы на существующие таблицы, но новые таблицы создаются без них. Это решается через `ALTER DEFAULT PRIVILEGES`.

```sql
-- Выполняется пользователем, который БУДЕТ создавать таблицы (или суперпользователем)
ALTER DEFAULT PRIVILEGES IN SCHEMA public 
GRANT SELECT ON TABLES TO read_only_group;
```

### Наследование через группы (рекомендуемый способ)
Использование групповых ролей упрощает администрирование: права назначаются группе, а пользователи просто включаются в эту группу.

1.  **Назначение прав группе:**
    ```sql
    GRANT SELECT ON TABLE my_table TO read_only_group;
    ```

2.  **Назначение группы пользователю:**
    ```sql
    GRANT read_only_group TO app_user;
    ```

### Безопасность: Row-Level Security (RLS)
RLS позволяет ограничить доступ к конкретным **строкам** в зависимости от того, какой пользователь выполняет запрос.

```sql
-- 1. Включение RLS для таблицы
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- 2. Создание политики (доступ только к своим заказам)
CREATE POLICY user_orders_policy ON orders
    FOR SELECT
    USING (user_id = current_user);

-- → результат: SELECT * FROM orders вернет только строки текущего пользователя.
```

## Изменение ролей и смена пароля
Для изменения параметров существующей роли используется `ALTER ROLE` или `ALTER USER`.

```sql
-- Смена пароля
ALTER USER app_user PASSWORD 'new_secure_pass';

-- Запрет входа в систему
ALTER ROLE app_user NOLOGIN;
```

## Администрирование и очистка

### Смена владельца (Ownership)
Если необходимо удалить пользователя, нужно сначала передать его объекты другому владельцу.
```sql
REASSIGN OWNED BY old_user TO new_admin;
DROP OWNED BY old_user;
DROP USER old_user;
```

## Доступ под новой ролью
Для подключения к `psql` под новой ролью без использования `sudo -u postgres`, в системе должен существовать одноименный пользователь Ubuntu.

1.  Создайте пользователя в ОС:
    ```bash
    sudo adduser app_user
    ```
2.  Подключитесь к БД:
    ```bash
    sudo -u app_user psql -d mydb
    ```
    Или, если вы уже вошли под этим пользователем:
    ```bash
    psql -d mydb
    ```

### См. также
*   [Основы работы в psql](./console_basics.md) — мета-команды инспекции ролей (`\du`, `\drds`).
*   [Наблюдаемость PostgreSQL](./observability.md) — настройка роли для мониторинга.
*   [Обзор PostgreSQL](../overview.md) — архитектура и основные возможности.
*   [Базовые операции с данными (CRUD)](./crud_operations.md) — использование прав в запросах.
