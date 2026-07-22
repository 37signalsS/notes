# Управление ролями и правами доступа в PostgreSQL

## Концепция ролей
В современных версиях PostgreSQL понятия «пользователь» и «группа» объединены в одну сущность — **Роль**. Разница между ними лишь в настройках:
*   **Пользователь:** Роль с атрибутом `LOGIN`, позволяющим подключаться к БД.
*   **Группа:** Роль без атрибута `LOGIN` (по умолчанию `NOLOGIN`), предназначенная для объединения прав и их наследования пользователями.

По умолчанию при установке создается системный пользователь и роль `postgres`.

## Работа с системной ролью postgres

### Вход через переключение пользователя
```bash
sudo -i -u postgres
psql
```

### Прямой вход через sudo
```bash
sudo -u postgres psql
```

**Базовые команды консоли psql:**
*   `\conninfo` — информация о текущем подключении.
*   `\help` — справка по SQL-командам.
*   `\?` — справка по командам psql.
*   `\q` — выход из консоли.

## Создание новых ролей

### Создание через SQL
SQL-команды `CREATE ROLE` и `CREATE USER` практически идентичны, за исключением значения параметра `LOGIN` по умолчанию.

```sql
-- Создание пользователя (LOGIN по умолчанию)
CREATE USER app_user WITH PASSWORD 'secure_pass' VALID UNTIL '2026-12-31';

-- Создание роли без права входа (групповая роль)
CREATE ROLE read_only_group;

-- Создание пользователя через CREATE ROLE (нужно явно указать LOGIN)
CREATE ROLE another_user LOGIN PASSWORD 'pass';
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

### Наследование через группы (рекомендуемый способ)
Использование групповых ролей упрощает администрирование: права назначаются группе, а пользователи просто включаются в эту группу.

1.  **Создание групп и назначение прав:**
    ```sql
    -- Права только на чтение
    GRANT SELECT ON TABLE my_table TO read_only_group;
    
    -- Полные права
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE my_table TO read_write_group;
    ```

2.  **Назначение группы пользователю:**
    ```sql
    GRANT read_only_group TO app_user;
    ```

3.  **Отзыв прав/группы:**
    ```sql
    -- Исключить пользователя из группы
    REVOKE read_only_group FROM app_user;
    
    -- Отозвать конкретное право у группы
    REVOKE UPDATE ON TABLE my_table FROM read_write_group;
    ```

### Прямое назначение прав
Вы можете назначить все привилегии на объект конкретному пользователю напрямую:
```sql
GRANT ALL PRIVILEGES ON TABLE second_table TO app_user;
```

## Изменение ролей и смена пароля
Для изменения параметров существующей роли используется `ALTER ROLE` или `ALTER USER`.

```sql
-- Смена пароля
ALTER USER app_user PASSWORD 'new_secure_pass';

-- Запрет входа в систему
ALTER ROLE app_user NOLOGIN;
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
*   [Базовые операции с данными (CRUD)](./crud_operations.md)
*   [Обзор PostgreSQL](../overview.md)
*   [Графические интерфейсы (pgAdmin)](./management_tools.md)
