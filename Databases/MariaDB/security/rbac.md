# Ролевая модель доступа (RBAC) в MariaDB

RBAC позволяет избежать хаоса в правах доступа, особенно в больших командах. Подробнее о похожих паттернах в MySQL: **[Управление ролями MySQL](../../MySQL/role_management.md)**.

## Создание и иерархия ролей

```sql
-- 1. Создание ролей
CREATE ROLE developer_role;
CREATE ROLE analyst_role;
CREATE ROLE lead_role;

-- 2. Назначение прав ролям
GRANT SELECT, INSERT, UPDATE ON project_db.* TO developer_role;
GRANT SELECT ON project_db.* TO analyst_role;

-- 3. Иерархия: Lead получает права Разработчика + дополнительные
GRANT developer_role TO lead_role;
GRANT DROP, ALTER ON project_db.* TO lead_role;
```

## Назначение ролей пользователям

```sql
-- Выдача роли пользователю
GRANT developer_role TO 'ivan'@'%';

-- Установка роли по умолчанию (чтобы права были активны сразу при входе)
SET DEFAULT ROLE developer_role FOR 'ivan'@'%';

-- Проверка активных ролей
SELECT CURRENT_ROLE();

-- Просмотр всех ролей пользователя
SHOW GRANTS FOR 'ivan'@'%';
```

## Управление ролями в рантайме

```sql
-- Включение всех ролей по умолчанию при входе (опционально, для удобства)
SET GLOBAL activate_all_roles_on_login = ON;

-- Временная активация дополнительной роли в сессии
SET ROLE analyst_role;
-- Теперь пользователь имеет пересечение прав developer_role И analyst_role

-- Сброс на роль по умолчанию
SET ROLE DEFAULT;

-- Отзыв роли у пользователя
REVOKE developer_role FROM 'ivan'@'%';

-- Удаление роли (только если она не назначена ни одному пользователю)
DROP ROLE developer_role;
```

## Паттерн: изоляция прикладных учётных записей

```sql
-- Приложение не должно иметь DDL-привилегий
CREATE ROLE app_readonly_role;
CREATE ROLE app_readwrite_role;

GRANT SELECT ON app_db.* TO app_readonly_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON app_db.* TO app_readwrite_role;

-- Создание пользователя приложения с ограничением по хосту
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'strong_password_here';
GRANT app_readwrite_role TO 'app_svc'@'10.0.5.%';
SET DEFAULT ROLE app_readwrite_role FOR 'app_svc'@'10.0.5.%';

-- Проверка: приложение НЕ должно иметь доступ к другим БД
SHOW GRANTS FOR 'app_svc'@'10.0.5.%' USING app_readwrite_role;
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Аутентификация](authentication.md)** — управление пользователями и плагинами аутентификации.
- **[Дополнительные параметры](additional-parameters.md)** — чистка от ненужных привилегий.
- **[Управление ролями MySQL](../../MySQL/role_management.md)** — сравнение RBAC в MySQL и MariaDB.
