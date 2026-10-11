# Ролевая модель доступа (RBAC) в MariaDB

**Актуально для:** MariaDB 10.0+ / 10.5+ / 11.x / 12.x

## Определения

**RBAC (Role-Based Access Control)** — модель разграничения прав доступа, при которой привилегии назначаются именованным ролям, а роли — пользователям. Это позволяет управлять правами централизованно и избегать хаоса прямых `GRANT` в больших командах.

**Роль (Role)** — именованный набор привилегий. Технически роль в MariaDB — это учетная запись без возможности аутентификации (`NOLOGIN`), предназначенная исключительно для группировки прав.

**Активная роль (Active Role)** — роль, привилегии которой действуют в рамках текущей сессии. После назначения роли пользователю она неактивна по умолчанию и требует явной активации.

**Привилегия (Privilege)** — разрешение на выполнение конкретного действия: `SELECT`, `INSERT`, `CREATE`, `SUPER` и т.д. Привилегии могут быть глобальными (`*.*`), на уровне схемы (`db.*`), таблицы (`db.table`), столбца или хранимой процедуры.

**Иерархия ролей (Role Hierarchy)** — механизм, при котором одна роль может наследовать права другой через `GRANT role_a TO role_b`. Пользователь, назначенный на `role_b`, получает объединение прав обеих ролей.

**Принцип наименьших привилегий (PoLP)** — предоставление пользователям и сервисам только тех прав, которые минимально необходимы для их функций. В MariaDB реализуется через гранулярные `GRANT`/`REVOKE`, роли и запрет прямых привилегий у прикладных аккаунтов.

**Service Account (Сервисный аккаунт)** — учетная запись, используемая приложениями, мониторингом, репликацией или оркестраторами вместо индивидуальных пользователей. Должна иметь строго ограниченный набор привилегий и ограничение по хосту.

## Базовые концепции

### Архитектура RBAC в MariaDB

MariaDB внедрила полноценную поддержку ролей в версии 10.0, значительно раньше MySQL. Ключевые особенности:

1. **Роли как объекты:** `CREATE ROLE` создаёт именованный контейнер привилегий. Роль нельзя использовать для входа в СУБД.
2. **Наследование:** `GRANT role_a TO role_b` создаёт иерархию. Привилегии суммируются при проверке доступа.
3. **Активация:** После `GRANT role TO user` права не действуют автоматически. Пользователь должен активировать роль через `SET ROLE` или глобальную переменную `activate_all_roles_on_login`.
4. **Хранение метаданных:** Сведения о ролях и назначениях хранятся в системных таблицах `mysql.user`, `mysql.role_edges`, `mysql.default_roles`.

### Жизненный цикл роли

1. **Создание:** `CREATE ROLE role_name;`
2. **Назначение привилегий:** `GRANT ... TO role_name;`
3. **Назначение пользователям:** `GRANT role_name TO 'user'@'host';`
4. **Активация:** `SET DEFAULT ROLE role_name FOR 'user'@'host';` или `SET ROLE role_name;`
5. **Аудит:** `SHOW GRANTS`, `SELECT * FROM mysql.role_edges;`
6. **Ротация/отзыв:** `REVOKE role_name FROM 'user'@'host';`
7. **Удаление:** `DROP ROLE role_name;` (только если роль не назначена никому).

### Механизм активации ролей

По умолчанию роли после назначения пользователю находятся в неактивном состоянии. Активация происходит одним из способов:

- **Сессионная активация:** `SET ROLE role_name;` — действует только в текущей сессии.
- **Активация по умолчанию:** `SET DEFAULT ROLE role_name FOR 'user'@'host';` — роль активируется автоматически при каждом входе.
- **Глобальная активация:** `SET GLOBAL activate_all_roles_on_login = ON;` — все назначенные пользователю роли активируются при входе.

## Предварительные требования

- **Версия MariaDB:** 10.0+ для базового RBAC, 10.5+ для стабильной работы с ролями в production.
- **Политика паролей:** Включите `validate_password` с длиной ≥ 14 символов. Пароли сервисных аккаунтов хранятся в секрет-менеджере, а не в конфигах.
- **Сеть:** Подключения к СУБД разрешены только из доверенных подсетей. Для административных подключений используйте `localhost` или jump-host.
- **Аутентификация:** Используйте `unix_socket` для локального root, `caching_sha2_password` или `ed25519` для сетевых аккаунтов. Подробнее: **[Аутентификация](authentication.md)**.
- **SSL/TLS:** Для всех роли с сетевыми подключениями требуйте SSL: `REQUIRE SSL`. Подробнее: **[SSL/TLS](ssl-tls.md)**.

## Практические сценарии

### 1. Создание и иерархия ролей

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

### 2. Назначение ролей пользователям

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

### 3. Управление ролями в рантайме

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

### 4. Паттерн: изоляция прикладных учётных записей

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

### 5. Сервисные учётные записи

Для инфраструктурных компонентов создавайте отдельных пользователей с минимальными привилегиями. Ниже — типовые паттерны, детализированные в соответствующих разделах:

| Сервисный аккаунт | Назначение | Ключевые привилегии | Детали |
| :--- | :--- | :--- | :--- |
| `monitor` | Сбор метрик Prometheus, проверка здоровья | `REPLICATION CLIENT`, `PROCESS`, `SHOW DATABASES`, `SHOW VIEW`, `SELECT ON performance_schema.*`, `SLAVE MONITOR` | **[Мониторинг MariaDB](../monitoring.md#создание-пользователя-для-мониторинга)** |
| `repl_user` | Репликация Source-Replica / Galera | `REPLICATION SLAVE ON *.*` | **[Настройка репликации](../replication/setup_guide.md#создание-пользователя-для-репликации-на-источнике)** |
| `maxscale_user` | Управление MariaDB MaxScale | `RELOAD`, `SUPER`, `SELECT ON mysql.*` | **[MaxScale Overview](../MaxScale/maxscale_overview.md#11-привилегии-сервисного-пользователя)** |
| `backup_user` | Логические/физические бэкапы | `SELECT`, `LOCK TABLES`, `SHOW VIEW`, `EVENT`, `TRIGGER`, `REPLICATION CLIENT` | См. также **[Бэкапы](../backup_and_recovery.md)** |

### 6. Очистка от прямых привилегий (PoLP enforcement)

```sql
-- Поиск пользователей с опасными глобальными привилегиями
SELECT User, Host, Super_priv, File_priv, Process_priv
FROM mysql.user
WHERE Super_priv = 'Y' OR File_priv = 'Y';

-- Поиск прямых GRANT-ов, минуя роли
SELECT DISTINCT USER, HOST
FROM mysql.db
WHERE Db NOT IN ('information_schema','performance_schema','mysql','sys');

-- Отзыв опасных привилегий у прикладного пользователя
REVOKE Super_priv, File_priv, Process_priv ON *.* FROM 'app_svc'@'10.0.5.%';

-- Проверка итоговых прав (с учётом ролей)
SHOW GRANTS FOR 'app_svc'@'10.0.5.%' USING app_readwrite_role;
```

## Верификация RBAC

```sql
-- Список всех ролей на инстансе
SELECT * FROM mysql.user WHERE password = '' AND account_locked = 'N';

-- Назначения ролей пользователям
SELECT * FROM mysql.role_edges;

-- Роли по умолчанию
SELECT * FROM mysql.default_roles;

-- Активные роли в текущей сессии
SELECT CURRENT_ROLE();

-- Полный список привилегий пользователя (с учётом ролей)
SHOW GRANTS FOR 'ivan'@'%';
SHOW GRANTS FOR 'ivan'@'%' USING analyst_role;
```

## Аудит

Для соответствия PCI DSS, GDPR и ФСТЭК настройте `server_audit` plugin на логирование изменений ролей и привилегий:

```ini
[mariadb]
plugin_load_add = server_audit
server_audit = FORCE_PLUS_PERMANENT
server_audit_logging = ON
server_audit_events = CONNECT,QUERY,TABLE,QUERY_DDL
server_audit_excl_users = 'zabbix,repl_user,maxscale'
server_audit_output_type = SYSLOG
server_audit_syslog_facility = LOG_LOCAL6
```

Периодически выполняйте обзор `mysql.role_edges` и `SHOW GRANTS` для выявления неиспользуемых ролей и избыточных привилегий. Подробнее: **[Аудит](audit.md)**.

## Безопасность хранимых объектов

Хранимые процедуры, функции, представления и триггеры выполняются с привилегиями своего создателя (по умолчанию) — это отдельный вектор эскалации привилегий.

### DEFINER vs INVOKER

```sql
-- Процедура выполняется от имени создателя (DEFINER) — по умолчанию
CREATE DEFINER=`admin`@`localhost` PROCEDURE app_db.get_stats()
SQL SECURITY DEFINER
BEGIN
  SELECT * FROM app_db.secret_table;
END;

-- Процедура выполняется от имени вызывающего (INVOKER) — безопаснее
CREATE PROCEDURE app_db.get_stats()
SQL SECURITY INVOKER
BEGIN
  SELECT * FROM app_db.public_table;
END;
```

**Правила:**
- `SQL SECURITY DEFINER` — процедура работает с привилегиями DEFINER; вызывающий получает доступ к объектам, к которым у него нет прямых прав. Используйте только когда это необходимо.
- `SQL SECURITY INVOKER` — процедура работает с привилегиями вызывающего; безопаснее по умолчанию.
- Аудит DEFINER-объектов: `SELECT ROUTINE_SCHEMA, ROUTINE_NAME, SECURITY_TYPE, DEFINER FROM information_schema.ROUTINES WHERE SECURITY_TYPE = 'DEFINER';`

### Контроль создания хранимых объектов

```ini
[mariadb]
# Запрет создания хранимых функций без SUPER (по умолчанию OFF)
# При ON — любой пользователь с CREATE ROUTINE может создавать функции
log_bin_trust_function_creators = OFF
```

**Пояснения:**
- `log_bin_trust_function_creators = OFF` (дефолт) требует `SUPER` для создания функций при включённом binlog — защита от недетерминированных функций в репликации.
- Выдача `CREATE ROUTINE` — через роли, не глобально.

Подробнее о хранимых объектах: [Безопасность хранимых объектов](../../Concepts/stored_objects/security.md).

## Маскирование данных (Data Masking)

MariaDB Community не имеет нативного data masking. Реализуется через представления и колоночные привилегии; в MariaDB MaxScale — встроенный data masking.

### Маскирование через представления

```sql
-- Базовая таблица с ПДн
CREATE TABLE app_db.users (
  id INT PRIMARY KEY,
  full_name VARCHAR(100),
  phone VARCHAR(20),
  email VARCHAR(100)
);

-- Представление с маскированием для аналитиков
CREATE VIEW app_db.users_masked AS
SELECT
  id,
  CONCAT(LEFT(full_name, 1), '***') AS full_name,
  CONCAT('+7 (***) ***-', RIGHT(phone, 2)) AS phone,
  CONCAT('***@', SUBSTRING_INDEX(email, '@', -1)) AS email
FROM app_db.users;

-- Аналитики получают доступ только к представлению
CREATE ROLE analyst_role;
GRANT SELECT ON app_db.users_masked TO analyst_role;
-- НЕ выдавайте SELECT на app_db.users
```

### Колоночные привилегии

```sql
-- Доступ только к конкретным столбцам
GRANT SELECT (id, full_name) ON app_db.users TO 'analyst'@'10.0.5.%';

-- Проверка
SHOW GRANTS FOR 'analyst'@'10.0.5.%';
-- → GRANT SELECT (id, full_name) ON `app_db`.`users` TO `analyst`@`10.0.5.%`
```

**Пояснения:**
- Колоночные привилегии хранятся в `mysql.columns_priv`.
- Допустимые привилегии на уровне столбцов: `INSERT`, `REFERENCES`, `SELECT`, `UPDATE`.
- `SELECT` на подмножестве столбцов: `WHERE`/`ORDER BY`/`GROUP BY` по недоступным столбцам вернёт ошибку.

### Маскирование через MaxScale

MariaDB MaxScale поддерживает нативный data masking (регулярные выражения, хеширование) на уровне прокси — без изменения приложения. Подробнее: [MaxScale: безопасность и шифрование](../MaxScale/maxscale_overview.md#безопасность-и-шифрование).

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Access denied` после `GRANT` | Права роли неактивны | Выполните `SET ROLE ALL;` или установите `SET DEFAULT ROLE` |
| `ERROR 1396` при `GRANT` | Пользователь не существует | Создайте пользователя: `CREATE USER 'u'@'h' IDENTIFIED BY 'p';` |
| `ERROR 3510` при `DROP ROLE` | Роль назначена пользователям | `REVOKE role FROM user;` для всех пользователей, затем `DROP ROLE` |
| `Access denied` для сервисного аккаунта | Недостаточно привилегий на системные таблицы | Выдайте `SELECT ON mysql.*` или конкретные динамические привилегии |
| Потеря прав после перезапуска | Не установлена роль по умолчанию | Выполните `SET DEFAULT ROLE role_name FOR 'user'@'host';` |
| `SHOW GRANTS` не показывает права роли | Пропущено `USING role_name` | Используйте `SHOW GRANTS FOR 'user'@'host' USING role_name;` |

## Лучшие практики

1. **Никаких прямых `GRANT` приложениям.** Все права выдаются через роли. Прямые `GRANT` усложняют аудит и ротацию.
2. **Ограничение по хосту.** Всегда указывайте конкретный хост или подсеть вместо `%` для сервисных аккаунтов.
3. **Минимальные глобальные привилегии.** Запретите `SUPER`, `FILE`, `PROCESS` для прикладных пользователей. Используйте гранулярные привилегии на уровне схем/таблиц.
4. **Ротация паролей.** Для сервисных аккаунтов используйте `PASSWORD EXPIRE INTERVAL 90 DAY` или внешний секрет-менеджер.
5. **Аудит `mysql.role_edges`.** Раз в квартал проверяйте иерархию ролей на наличие устаревших связей.
6. **Включите `activate_all_roles_on_login`.** Устраняет человеческий фактор при забывании `SET ROLE`.
7. **Отдельные окружения.** Разные наборы ролей для dev/staging/prod. Не экспортируйте production-роли в тестовые среды.
8. **Документируйте карту доступа.** Ведите актуальный список сервисных аккаунтов, их ролей и владельцев.

## Ограничения

- **SUPER_priv:** Наличие `SUPER` у пользователя обходит большинство проверок RBAC. Избегайте назначения `SUPER` сервисным аккаунтам.
- **Репликация:** Изменения в `mysql.user`, `mysql.db` и ролях реплицируются как DDL. При использовании GTID убедитесь, что изменения применяются на всех узлах кластера.
- **Даунгрейд:** После создания ролей и назначения привилегий откат на версию < 10.0 невозможен — системные таблицы изменены.
- **Метаданные в дампах:** `mysqldump` по умолчанию экспортирует роли и `GRANT`-ы. При импорте в другой инстанс убедитесь, что роли и пользователи существуют.

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Аутентификация](authentication.md)** — управление пользователями и плагинами аутентификации.
- **[Дополнительные параметры](additional-parameters.md)** — чистка от ненужных привилегий.
- **[Аудит](audit.md)** — логирование изменений в RBAC через `server_audit`.
- **[Мониторинг MariaDB](../monitoring.md)** — пользователь для сбора метрик.
- **[Настройка репликации](../replication/setup_guide.md)** — пользователь репликации.
- **[MaxScale Overview](../MaxScale/maxscale_overview.md)** — сервисный пользователь прокси.
- **[Управление ролями MySQL](../../MySQL/role_management.md)** — сравнение RBAC в MySQL и MariaDB.
