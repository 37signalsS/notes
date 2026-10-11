# Управление ролями и доступом в MySQL 8.0+ (RBAC)

**Актуально для:** MySQL 8.0 / 8.4 LTS

## Определения

*   **RBAC (Role-Based Access Control)** — модель управления доступом, при которой права назначаются не конкретным пользователям, а ролям. Пользователи получают права путем «наследования» закрепленных за ними ролей.
*   **Роль (Role)** — именованный набор привилегий. В MySQL роль технически является учетной записью без возможности входа (`NOLOGIN`), предназначенной для группировки прав.
*   **Активная роль (Active Role)** — роль, привилегии которой действуют в рамках текущей сессии пользователя. По умолчанию роли после назначения пользователю находятся в неактивном состоянии.
*   **Динамические привилегии (Dynamic Privileges)** — расширяемый набор прав, введенный в MySQL 8.0 для гранулярного контроля над системными операциями (например, `BACKUP_ADMIN`, `SYSTEM_VARIABLES_ADMIN`), заменяющий избыточную привилегию `SUPER`.
*   **Обязательная роль (Mandatory Role)** — роль, которая автоматически активна для всех пользователей и от которой они не могут отказаться. Назначается через `mandatory_roles` в `my.cnf` или системную таблицу.
*   **Жизненный цикл учетной записи (Account Lifecycle)** — последовательность состояний: создание → назначение ролей → использование → ротация пароля → блокировка/удаление.
*   **Ограничение подключений (Connection Limit)** — максимальное количество одновременных сессий для пользователя/роли, задаваемое через `MAX_USER_CONNECTIONS` или `MAX_CONNECTIONS_PER_HOUR`.

## Базовые концепции

### Модель наследования

В MySQL 8.0 роли могут быть назначены пользователям или другим ролям, создавая иерархию. Привилегии суммируются: если пользователю назначены две роли с разными правами, он получает объединение этих прав.

**Важно:** Назначение роли пользователю не означает автоматическую активацию. Права роли действуют только после `SET ROLE` или включения глобальной переменной.

### Механизм активации

После выполнения `GRANT 'role_name' TO 'user_name'`, права роли не начинают действовать автоматически. Пользователь должен активировать их:
1.  **Вручную:** `SET ROLE 'role_name';` или `SET ROLE ALL;`
2.  **Автоматически (Рекомендуется):** Через системную переменную `activate_all_roles_on_login = ON`.

### Предпосылки и требования (Prerequisites)

**Инфраструктура и ОС:**
- **MySQL**: Версия 8.0.11+ для RBAC, 8.0.27+ для многофакторной аутентификации, 8.4 LTS для долгосрочной поддержки.
- **Файловая система**: Права на `datadir` — `mysql:mysql`, `chmod 750`. Секреты и пароли не должны храниться в world-readable файлах.
- **Плагины**: Убедитесь, что плагины `validate_password` и `connection_control` установлены для принудительной политики паролей и защиты от перебора.
- **Сеть**: Порт 3306/tcp открыт только для подсетей приложений. Для административных подключений используйте localhost или jump-host.
- **NTP**: Синхронизация времени обязательна. Расхождение > 100 ms ломает проверку срока действия паролей и аудит.

**Политика паролей:**
- Установите `validate_password.policy = STRONG` с длиной ≥ 14 символов.
- Настройте `PASSWORD EXPIRE INTERVAL 90 DAY` для сервисных аккаунтов.
- Включите `FAILED_LOGIN_ATTEMPTS 5` и `PASSWORD_LOCK_TIME 2` для блокировки после неудачных входов.

### Жизненный цикл пользователей (SRE-паттерн)

1.  **Создание**: Используйте `CREATE USER` с явным указанием хоста, плагина аутентификации, требования SSL, срока действия пароля и ограничения по подключениям.
2.  **Назначение ролей**: `GRANT role TO user` + `ALTER USER DEFAULT ROLE role`.
3.  **Ротация**: Периодическая смена паролей через `ALTER USER ... IDENTIFIED BY` или автоматически через внешний секрет-менеджер.
4.  **Аудит**: Регулярный обзор `mysql.user` и `INFORMATION_SCHEMA.APPLICABLE_ROLES` на предмет неиспользуемых аккаунтов.
5.  **Деактивация**: `ALTER USER ... ACCOUNT LOCK` вместо удаления для сохранения истории.
6.  **Удаление**: `DROP USER` только после подтверждения, что аккаунт не используется и нет зависимых объектов.

## Практические сценарии

### 1. Создание и назначение ролей

**Задача:** Создать роли для_read и write доступа, назначить их пользователям с разными хостами.

```sql
-- 1. Создание ролей
CREATE ROLE 'developer_read', 'app_writer';

-- 2. Назначение привилегий ролям
GRANT SELECT ON app_db.* TO 'developer_read';
GRANT INSERT, UPDATE, DELETE ON app_db.* TO 'app_writer';
GRANT PROCESS ON *.* TO 'developer_read';

-- 3. Создание пользователя с ограничением по хосту и подключениям
CREATE USER 'dev_user'@'10.0.%' IDENTIFIED BY 'secure_password'
  REQUIRE SSL
  WITH MAX_USER_CONNECTIONS 10;

-- 4. Назначение ролей и установка роли по умолчанию
GRANT 'developer_read' TO 'dev_user'@'10.0.%';
ALTER USER 'dev_user'@'10.0.%' DEFAULT ROLE 'developer_read';
```

### 2. Использование обязательных ролей (Mandatory Roles)

SRE-паттерн: автоматическое назначение роли аудита всем пользователям системы.

```ini
# В файле my.cnf
[mysqld]
mandatory_roles = 'role_audit@localhost,role_security_monitor'
```

*Важно: Пользователи не могут отказаться от mandatory roles, и эти роли всегда активны при логине. Это обеспечивает точечный аудит без зависимости от конфигурации клиента.*

### 3. Отказ от SUPER в пользу динамических привилегий

В MySQL 8.0 привилегия `SUPER` считается устаревшей (deprecated). Вместо неё следует использовать:
*   `SYSTEM_VARIABLES_ADMIN` — изменение глобальных переменных.
*   `BINLOG_ADMIN` — управление бинарными логами.
*   `SERVICE_CONNECTION_ADMIN` — доступ к серверу при достижении `max_connections`.
*   `CLONE_ADMIN` — инициализация клонирования данных.

```sql
-- Пример: роль для операций обслуживания (SRE)
CREATE ROLE 'ops_maintenance';
GRANT SYSTEM_VARIABLES_ADMIN, PERSIST_RO_VARIABLES_ADMIN ON *.* TO 'ops_maintenance';
GRANT RELOAD ON *.* TO 'ops_maintenance';

-- Пример: роль для бэкапов
CREATE ROLE 'backup_agent';
GRANT BACKUP_ADMIN, SESSION_VARIABLES_ADMIN ON *.* TO 'backup_agent';
GRANT SELECT ON *.* TO 'backup_agent';
GRANT REPLICATION CLIENT ON *.* TO 'backup_agent';
```

### 4. Управление парольной политикой и блокировкой аккаунтов

```sql
-- Установка политики сложности паролей
INSTALL COMPONENT 'file://component_validate_password';

SET PERSIST validate_password.policy = STRONG;
SET PERSIST validate_password.length = 14;
SET PERSIST validate_password.mixed_case_count = 1;
SET PERSIST validate_password.number_count = 1;
SET PERSIST validate_password.special_char_count = 1;

-- Защита от подбора паролей
INSTALL PLUGIN CONNECTION_CONTROL SONAME 'connection_control.so';
INSTALL PLUGIN CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS SONAME 'connection_control_failed_login_attempts.so';

SET GLOBAL connection_control_failed_connections_threshold = 10;
SET GLOBAL connection_control_min_connection_delay = 2000;
SET GLOBAL connection_control_max_connection_delay = 3600000;

-- Создание пользователя с политикой срока действия
CREATE USER 'svc_app'@'10.0.%' IDENTIFIED BY 'Str0ng-P@ssw0rd!'
  REQUIRE SSL
  PASSWORD EXPIRE INTERVAL 90 DAY
  PASSWORD HISTORY 5
  PASSWORD REUSE INTERVAL 365 DAY
  FAILED_LOGIN_ATTEMPTS 5
  PASSWORD_LOCK_TIME 2
  WITH MAX_USER_CONNECTIONS 50;

-- Временная блокировка аккаунта (например, при расследовании инцидента)
ALTER USER 'svc_app'@'10.0.%' ACCOUNT LOCK;
```

### 5. Аудит привилегий и обзор доступа

```sql
-- Все пользователи и их плагины аутентификации
SELECT user, host, plugin, account_locked, password_expired
FROM mysql.user
ORDER BY user;

-- Пользователи с доступом извне (не localhost)
SELECT user, host, account_locked
FROM mysql.user
WHERE host NOT IN ('localhost', '127.0.0.1', '::1')
  AND host NOT LIKE '10.%'
  AND host NOT LIKE '192.168.%';

-- Избыточные привилегии на уровне таблиц (поиск нарушений least privilege)
SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.SCHEMA_PRIVILEGES
WHERE grantee NOT LIKE 'mysql.%'
ORDER BY grantee, table_schema;

-- Статус SSL для активных подключений
SELECT user, host, ssl_cipher, tls_version
FROM performance_schema.ssl_account_status
WHERE ssl_cipher IS NOT NULL;

-- Источник подключений по подсетям
SELECT SUBSTRING_INDEX(host, '.', 3) AS subnet, COUNT(*) AS connections
FROM information_schema.PROCESSLIST
GROUP BY subnet
ORDER BY connections DESC;
```

### 6. Управление ролями через Infrastructure as Code (SRE-паттерн)

```yaml
# Пример: декларативное определение ролей в Ansible
- name: Create application read-only role
  community.mysql.mysql_user:
    name: app_svc_ro
    host: "%"
    priv: "app_db.*:SELECT"
    state: present
    login_user: admin
    login_password: "{{ admin_password }}"

- name: Grant role to application user
  community.mysql.mysql_user:
    name: web_app
    host: "10.0.%"
    role:
      - app_svc_ro
    state: present
    login_user: admin
    login_password: "{{ admin_password }}"
```

**Важно:** Храните определения ролей и пользователей в git-репозитории. Избегайте ручного выполнения `GRANT`/`CREATE USER` на Production — все изменения должны проходить через CI/CD.

## Валидация и проверка

1.  **Проверка текущих активных ролей:**
    ```sql
    SELECT CURRENT_ROLE();
    -- → активные роли в текущей сессии
    ```

2.  **Просмотр графа ролей (иерархии):**
    ```sql
    SHOW GRANTS FOR 'dev_user'@'10.0.%' USING 'developer_read';
    -- → GRANT ... ON app_db.* TO 'dev_user'@'10.0.%'
    ```

3.  **Анализ привилегий через информационную схему:**
    ```sql
    SELECT * FROM INFORMATION_SCHEMA.APPLICABLE_ROLES;
    -- → список всех доступных пользователю ролей
    ```

4.  **Проверка политики паролей:**
    ```sql
    SHOW VARIABLES LIKE 'validate_password%';
    -- → validate_password.policy: STRONG
    -- → validate_password.length: 14
    ```

5.  **Проверка статуса аккаунта:**
    ```sql
    SELECT user, host, account_locked, password_expired
    FROM mysql.user
    WHERE user = 'svc_app';
    -- → account_locked: N, password_expired: N
    ```

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Роль назначена, но права не действуют** | Роль не активирована в сессии. | Выполните `SET ROLE ALL;` или установите `activate_all_roles_on_login = ON`. Проверьте `SELECT CURRENT_ROLE();`. |
| **`Access denied` при создании роли** | Недостаточно привилегий для `CREATE ROLE` или `GRANT`. | Необходима привилегия `CREATE ROLE` или `SUPER`. В 8.0+ используйте `SYSTEM_VARIABLES_ADMIN` вместо `SUPER`. |
| **Ошибка при удалении роли** | На роль завязаны обязательные роли (`mandatory_roles`). | Сначала удалите роль из списка `mandatory_roles` в конфигурации или системной таблице. |
| **`Access denied` при изменении переменной** | Недостаточно динамических привилегий (вместо `SUPER`). | Назначьте `SYSTEM_VARIABLES_ADMIN` или `PERSIST_RO_VARIABLES_ADMIN` соответствующей роли. |
| **Пользователь не может подключиться после смены пароля** | Пароль истек, аккаунт заблокирован, или неверный плагин аутентификации. | Проверьте `account_locked`, `password_expired` в `mysql.user`. Проверьте `plugin` для пользователя. |
| **Роль не применяется к новым подключениям** | `activate_all_roles_on_login` не установлена глобально, и клиент не вызывает `SET ROLE`. | Установите `SET PERSIST activate_all_roles_on_login = ON;` или обновите конфигурацию приложения. |
| **Split-horizon DNS ломает хосты** | `skip_name_resolve = ON`, но пользователь создан с доменным именем. | Создайте пользователя с IP-адресом или уберите `skip_name_resolve` (не рекомендуется для Production). |
| **Не могу назначить роль, которая уже существует как пользователь** | Имена ролей и пользователей хранятся в одной таблице `mysql.user`. | Переименуйте роль или пользователя. Избегайте совпадения имен в разных пространствах. |

## Рекомендации SRE

1.  **Принцип наименьших привилегий:** Никогда не используйте `root` для приложений. Создавайте гранулярные роли (`app_svc_ro`, `app_svc_rw`, `backup_agent`, `monitor`).
2.  **Автоматизация:** Управляйте ролями через IaC (Ansible, Terraform, Puppet). Храните определения в git-репозитории. Избегайте ручного выполнения `GRANT` на Production.
3.  **Аудит:** Используйте `audit_log` plugin в связке с ролями для отслеживания того, кто и когда выполнял деструктивные операции. См. **[Безопасность MySQL](./security.md)**.
4.  **Именование:** Используйте префиксы для ролей (например, `rl_` для ролей, `u_` для пользователей), чтобы избежать путаницы в логах и запросах.
5.  **Хосты:** Никогда не используйте `'user'@'%'` в Production. Ограничивайте доступ подсетью приложения (`'svc_app'@'10.0.%'`) или конкретными узлами. Для администраторов — только `localhost` или jump-host.
6.  **Ротация:** Настройте автоматическую ротацию паролей через внешний секрет-менеджер (HashiCorp Vault или собственное решение). См. раздел 4.
7.  **Мониторинг:** Интегрируйте проверки `APPLICABLE_ROLES` и `mysql.user` в регулярные cron-задачи или Grafana-дашборды. См. **[Мониторинг MySQL](./monitoring.md)**.
8.  **Резервное копирование:** Пользователи и привилегии хранятся в `mysql` базе данных. Убедитесь, что бэкап включает `mysql.*` таблицы. См. **[Резервное копирование MySQL](./backup_and_recovery/overview.md)**.
9.  **Миграция с 5.7:** В 5.7 нет ролей. При миграции на 8.0 создайте соответствующие роли, назначьте их пользователям и удалите прямые `GRANT` у пользователей.
10. **Обязательные роли:** Используйте `mandatory_roles` для аудита и безопасности, но ограничьте их минимально необходимыми правами, чтобы не создавать неожиданный side effects.
11. **SSL/TLS:** Всегда добавляйте `REQUIRE SSL` при создании пользователей, подключающихся по сети. Для внутренних сервисных аккаунтов можно использовать `REQUIRE X509` для mutual TLS.
12. **Connection Limits:** Устанавливайте `MAX_USER_CONNECTIONS` для сервисных аккаунтов, чтобы предотвратить утечку соединений и истощение `max_connections`.

## Краевые случаи (Edge Cases)

- **Имена ролей и пользователей:** MySQL хранит роли и пользователей в одной таблице `mysql.user`. Нельзя создать роль и пользователя с одинаковым именем. При миграции проверьте наличие коллизий.
- **Mandatory roles и DROP:** Нельзя удалить роль, указанную в `mandatory_roles`. Сначала удалите её из конфигурации и перезапустите сервер или очистите системную таблицу.
- **`activate_all_roles_on_login` в Production:** Глобальная активация ролей упрощает конфигурацию, но может привести к unexpected behavior если у пользователя назначены конфликтующие роли. Тестируйте изменения в staging.
- **Роли в репликации:** Пользователи и роли создаются на мастере и реплицируются на реплики. Но `mandatory_roles` в `my.cnf` необходимо дублировать на каждый узел. При использовании Group Replication убедитесь, что все узлы имеют одинаковую политику.
- **Миграция с 5.7:** В 5.7 нет RBAC. После обновления на 8.0:
  1. Создайте роли, соответствующие существующим группам прав.
  2. Назначьте роли пользователям.
  3. Убедитесь, что `activate_all_roles_on_login = ON` или приложения вызывают `SET ROLE`.
  4. Удалите прямые `GRANT` у пользователей, оставив только `GRANT role TO user`.
- **Взаимодействие с ProxySQL:** Если используется ProxySQL, роли MySQL не пересекаются с пользователями ProxySQL. Создавайте отдельного пользователя MySQL с минимальными правами для ProxySQL monitor. См. **[ProxySQL: L7-балансировка](./ProxySQL/proxysql_overview.md)**.
- **Сервисные аккаунты в Docker/Kubernetes:** При запуске MySQL в контейнере убедитесь, что UID/GID пользователя `mysql` совпадает с правами на PVC/hostPath. См. **[Запуск MySQL в Docker](./docker.md)**.

## Дополнительная информация

### См. также

- **[Обзор MySQL](./overview.md)** — архитектура и основные возможности.
- **[Безопасная установка MySQL](./installation.md)** — первичная настройка безопасности.
- **[Безопасность MySQL](./security.md)** — TDE, TLS, аутентификация, audit_log, password policy.
- **[Мониторинг MySQL](./monitoring.md)** — пользователь `monitor` и привилегии для сбора метрик.
- **[Orchestrator: Failover и топология](./orchestrator.md)** — пользователь `orchestrator` и его привилегии.
- **[Резервное копирование MySQL](./backup_and_recovery/overview.md)** — пользователь для бэкапов и Clone Plugin.
- **[Репликация MySQL: Обзор](./replication/overview.md)** — пользователь `repl` и привилегии репликации.
- **[Управление ролями в PostgreSQL](../PostgreSQL/Operations/role_management.md)** — сравнение подходов к RBAC.
