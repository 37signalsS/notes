# Миграция с MySQL на MariaDB: Чек-лист и руководство

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS / 9.x → MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Миграция (Migration)** — процесс переноса данных, схемы и конфигурации с одной СУБД на другую. В контексте MySQL -> MariaDB подразумевает переход с коммерческой СУБД Oracle на полностью открытую альтернативу.
*   **Логическая миграция (Logical Migration)** — перенос данных через экспорт в SQL-команды или промежуточные форматы (CSV/JSON). Единственный надежный способ перехода между MySQL 8.x+ и современными версиями MariaDB.
*   **Физическая миграция (Physical Migration)** — прямое копирование файлов данных (`/var/lib/mysql`) между серверами. Возможно только между совместимыми версиями MySQL и MariaDB (MySQL 5.7 -> MariaDB 10.x). Начиная с MySQL 8.0+, физическая миграция невозможна из-за несовместимости форматов.
*   **GTID (Global Transaction ID)** — уникальный идентификатор транзакции. В MariaDB и MySQL реализован по-разному, что делает невозможной прямую бинарную репликацию между ними в новых версиях.
*   **mydumper/myloader** — многопоточные альтернативы `mariadb-dump`/`mariadb-import`. Ускоряют экспорт/импорт в 5-10 раз за счет параллелизации, но требуют идентичной структуры на источнике и приемнике.
*   **MariaDB Foundation** — организация, поддерживающая MariaDB как полностью открытую альтернативу MySQL. Гарантирует независимость проекта от коммерческих интересов.
*   **caching_sha2_password** — метод аутентификации по умолчанию в MySQL 8.0+. Несовместим с MariaDB по умолчанию. Требует либо переключения на `mysql_native_password`, либо использования TLS для аутентификации.
*   **Runbook** — пошаговая инструкция, описывающая процедуры миграции, критерии валидации и шаги отката. Обязательный артефакт для SRE-команды.
*   **Change Advisory Board (CAB)** — функциональное подразделение или процесс, отвечающий за оценку рисков, согласование окон обслуживания и утверждение планов изменений в production-среде.

---

## Базовые концепции

### Почему требуется логическая миграция?

Начиная с MySQL 8.0 и MariaDB 10.5+, пути развития этих СУБД разошлись настолько, что бинарная совместимость файлов данных (`/var/lib/mysql`) и форматов репликации была нарушена.

1.  **Формат бинарного лога:** MariaDB внедряет дополнительные метаданные для поддержки своих движков (Aria, MyRocks). MySQL использует собственный формат для Group Replication.
2.  **Системные таблицы:** Структура базы `mysql` (пользователи, права, плагины) кардинально различается. MySQL 8.0 использует `caching_sha2_password` и `mysql_native_password`, тогда как MariaDB поддерживает `ed25519`, `unix_socket` и собственные плагины.
3.  **GTID:** MySQL использует UUID-базированный GTID (`source_id:transaction_id`), в то время как MariaDB использует тройку `domain_id:server_id:sequence_number`. Эти форматы полностью несовместимы.
4.  **JSON:** MySQL хранит JSON в бинарном формате (BLOB с внутренней структурой). MariaDB хранит JSON как псевдоним для `LONGTEXT` с автоматической проверкой `CHECK (JSON_VALID(...))`. Функции SQL совместимы, но производительность и физическое хранение различаются. Родная репликация по строкам (Row-Based Replication) из MySQL в MariaDB для столбцов JSON не работает без преобразования в `TEXT`.
5.  **Optimizer:** Различия в Cost-based Optimizer могут привести к тому, что один и тот же запрос будет выполняться по-разному на MySQL и MariaDB.

### Версионный маппинг

| Исходная версия MySQL | Целевая версия MariaDB | Рекомендация | Уровень сложности |
| :--- | :--- | :--- | :--- |
| MySQL 5.7 (EOL) | MariaDB 10.11 LTS | Самый стабильный путь перехода. Минимальные изменения в SQL-синтаксисе. | Низкий |
| MySQL 8.0 / 8.4 LTS | MariaDB 11.4 / 12.3 LTS | Требует тщательной проверки SQL-синтаксиса и типов данных. | Средний |
| MySQL 9.x Innovation | MariaDB 12.3 LTS | Возможны конфликты в новых функциях (Vector, JSON). Тщательное тестирование обязательно. | Высокий |

### Сравнение методов миграции

| Характеристика | mariadb-dump | mydumper/myloader | Физическое копирование |
| :--- | :--- | :--- | :--- |
| **Скорость** | Низкая (1 поток) | Высокая (8-16 потоков) | Очень высокая |
| **Блокировки** | `--single-transaction` для InnoDB | Аналогичные флаги | Блокирует запись |
| **Размер БД** | До 100 ГБ | От 50 ГБ | Без ограничений |
| **Совместимость** | Высокая (между версиями) | Высокая | Только совместимые версии |
| **Гибкость** | Высокая (фильтрация, модификация) | Средняя | Низкая |

---

## Предварительные требования (Prerequisites)

### Общие требования

1.  **Резервное копирование MySQL:** Создайте полный бэкап перед началом миграции. Используйте `mysqldump` с флагами `--single-transaction --routines --triggers --events`. Подробности см. в **[Резервное копирование MariaDB](../backup_and_recovery.md)**.
2.  **Тестовая среда:** Воспроизведите миграцию в staging перед выполнением в production.
3.  **Анализ зависимостей:** Проверьте, какие приложения используют MySQL, и убедитесь, что они поддерживают MariaDB.
4.  **Окно миграции:** Определите время простоя (если требуется) и уведомите заинтересованные стороны.
5.  **Мониторинг:** Убедитесь, что система мониторинга работает и вы будете отслеживать ключевые метрики.

### Change Management и коммуникация

Перед началом миграции убедитесь, что:
*   Окно обслуживания согласовано с бизнес-командами и заинтересованными сторонами.
*   Определен пункт отказа (stop-loss): если во время миграции возникает неразрешимая ошибка — немедленно переходите к откату.
*   Уведомлены все команды (SRE, Development, Support) о предстоящем изменении и потенциальном влиянии на latency.
*   Подготовлены каналы экстренной связи (Slack/Teams канал, телефонный emergency bridge).

### Проверка совместимости SQL

```bash
# На MySQL выполните проверку на наличие несовместимых функций
mysql -u root -p -e "
SELECT ROUTINE_NAME, ROUTINE_TYPE, DEFINER, SQL_DATA_ACCESS
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema')
ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME;
"

# Проверка триггеров
mysql -u root -p -e "
SELECT TRIGGER_NAME, EVENT_OBJECT_SCHEMA, EVENT_OBJECT_TABLE, ACTION_STATEMENT
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema');
"

# Проверка событий (Event Scheduler)
mysql -u root -p -e "
SELECT EVENT_SCHEMA, EVENT_NAME, EVENT_DEFINITION, STATUS
FROM information_schema.EVENTS
WHERE EVENT_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema');
"
```

### Проверка конфигурации MySQL

```bash
# Экспорт текущей конфигурации MySQL для анализа
mysql -u root -p -e "
SHOW VARIABLES WHERE Variable_name IN (
    'innodb_redo_log_capacity',
    'default_authentication_plugin',
    'sql_mode',
    'innodb_file_per_table',
    'character_set_server',
    'collation_server',
    'internal_tmp_mem_storage_engine'
);
"
```

### Проверка дискового пространства

```bash
# Проверка свободного места на сервере MariaDB
df -h /var/lib/mysql

# Проверка размера баз данных MySQL
mysql -u root -p -e "
SELECT table_schema AS 'Database',
       ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)'
FROM information_schema.tables
GROUP BY table_schema
ORDER BY SUM(data_length + index_length) DESC;
"
```

**Минимальные требования:** Свободное дисковое пространство должно составлять минимум 2x от общего объема данных MySQL для временных файлов и дампа.

---

## Чек-лист подготовки (Mandatory)

### 1. Аутентификация и пользователи

*   **MySQL 8.x/9.x:** Использует `caching_sha2_password` по умолчанию.
*   **MariaDB:** По умолчанию использует `mysql_native_password` или `unix_socket`.
*   **Действие:** Перед миграцией убедитесь, что ваши клиенты поддерживают методы аутентификации MariaDB. Рекомендуется использовать `ed25519` в MariaDB для высокого уровня безопасности.
*   **Важно:** Хеши паролей из MySQL `caching_sha2_password` несовместимы с MariaDB. Пользователей придется пересоздать или сбросить пароли.

### 2. Системные переменные (my.cnf)

Многие параметры MySQL 8.x/9.x не поддерживаются или называются иначе в MariaDB:
*   `innodb_redo_log_capacity` (MySQL) -> в MariaDB используйте классический `innodb_log_file_size` и `innodb_log_files_in_group`.
*   `default_authentication_plugin` (MySQL) -> `authentication_policy` (MariaDB 11.0+).
*   `internal_tmp_mem_storage_engine` (MySQL) -> в MariaDB аналогичную функцию выполняет `aria_used_for_temp_tables`.
*   `optimizer_switch` (MySQL) -> значения могут различаться.
*   **Действие:** Проверьте конфиг на наличие параметров, которые отличаются. Полный список см. в **[Конфигурация MariaDB](../configuration.md)**.

### 3. Типы данных и синтаксис

*   **JSON:** MariaDB хранит JSON как псевдоним для `LONGTEXT` с автоматической проверкой `CHECK (JSON_VALID(...))`. В MySQL это бинарный тип. При миграции функции `JSON_EXTRACT` работают одинаково, но производительность на огромных документах может отличаться.
*   **Spatial Indexes:** Реализация R-tree индексов различается. Пространственные функции совместимы, но индексы могут потребовать пересоздания.
*   **Ключевые слова:** Проверьте, не используете ли вы зарезервированные слова MariaDB в именах столбцов (например, `ROWS`).
*   **AUTO_INCREMENT:** Поведение идентично, но начальное значение может отличаться.

### 4. GTID и Репликация

*   Если MySQL был мастером в топологии Source-Replica, MariaDB-реплика не сможет подключиться через `SOURCE_AUTO_POSITION=1`.
*   **Действие:** Планируйте полный перезалив данных. Настройка репликации описана в **[Настройка репликации MariaDB](../replication/setup_guide.md)**.

### 5. Хранимые объекты

*   **Процедуры и функции:** Проверьте синтаксис. MySQL 8.0+ поддерживает CTE, Window Functions, которые также поддерживаются в MariaDB 10.2+. Однако, некоторые функции (например, `JSON_TABLE`) могут отличаться.
*   **Триггеры:** Синтаксис идентичен, но проверьте наличие функций, используемых в триггерах.
*   **Представления (Views):** Обычно мигрируются без проблем, если не используют MySQL-специфичные функции.

---

## Практический сценарий миграции

### Шаг 1: Подготовка MySQL

#### 1.1 Создание пользователя для дампа

```sql
-- На MySQL создайте пользователя с минимально необходимыми правами
CREATE USER 'migration_user'@'%' IDENTIFIED WITH mysql_native_password BY 'SecurePass123!';
GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON *.* TO 'migration_user'@'%';
FLUSH PRIVILEGES;
```

#### 1.2 Проверка целостности данных

```bash
# Проверьте количество таблиц и записей в каждой базе
mysql -u root -p -N -e "
SELECT table_schema, COUNT(*) AS table_count,
       SUM(table_rows) AS total_rows
FROM information_schema.tables
WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
GROUP BY table_schema;
"
# → result: | Database        | table_count | total_rows |
#           | my_app_db       | 45          | 1500000    |
```

### Шаг 2: Создание дампа на стороне MySQL

#### Вариант А: mariadb-dump (рекомендуется для БД до 100 ГБ)

```bash
# Создание дампа всех баз кроме системных
mariadb-dump -h source-mysql -u migration_user -p \
    --all-databases \
    --routines \
    --triggers \
    --events \
    --single-transaction \
    --hex-blob \
    --set-gtid-purged=OFF \
    --ignore-table=mysql.user \
    --ignore-table=mysql.db \
    --ignore-table=mysql.tables_priv \
    --ignore-table=mysql.columns_priv \
    --ignore-table=mysql.procs_priv \
    --ignore-table=mysql.proxies_priv \
    --ignore-table=mysql.role_edges \
    --ignore-table=mysql.default_roles \
    --ignore-table=mysql.password_history \
    --ignore-table=mysql.global_priv \
    --ignore-table=mysql.slow_log \
    --ignore-table=mysql.general_log \
    --ignore-table=mysql.slave_master_info \
    --ignore-table=mysql.slave_relay_log_info \
    --ignore-table=mysql.slave_worker_info \
    --ignore-table=mysql.gtid_executed \
    --ignore-table=mysql.innodb_index_stats \
    --ignore-table=mysql.innodb_table_stats \
    > full_dump.sql
```

**Примечание:** Мы игнорируем системные таблицы пользователей, так как их форматы несовместимы. Флаг `--set-gtid-purged=OFF` предотвращает включение GTID-позиций MySQL в дамп.

#### Вариант Б: mydumper (рекомендуется для БД от 50 ГБ)

```bash
# Установка mydumper (Debian/Ubuntu)
apt install mydumper

# Создание многопоточного дампа
mydumper \
    --host=source-mysql \
    --user=migration_user \
    --password=SecurePass123! \
    --threads=8 \
    --compress \
    --compress-algo=zstd \
    --chunk-filesize=64M \
    --long-query-guard=3600 \
    --skip-lock-tables \
    --no-locks \
    --outputdir=/data/migration/dump_$(date +%F)
```

**Примечание:** mydumper автоматически создает файл `metadata` с позицией бинарного лога, что упрощает проверку целостности.

### Шаг 3: Подготовка MariaDB

#### 3.1 Установка MariaDB

```bash
# Установка MariaDB 12.3 LTS
# Для Debian/Ubuntu:
apt install mariadb-server mariadb-client

# Для RHEL/CentOS:
dnf install mariadb-server mariadb

# Безопасная установка
mariadb-secure-installation
```

#### 3.2 Настройка конфигурации

```ini
# /etc/mysql/mariadb.conf.d/90-migration.cnf
[mariadb]
# Основные настройки
server_id               = 1
log_bin                 = /var/log/mysql/mariadb-bin
binlog_format           = ROW
gtid_domain_id          = 1

# Совместимость с MySQL (временная настройка для миграции)
sql_mode                = ""
character_set_server    = utf8mb4
collation_server        = utf8mb4_general_ci

# InnoDB настройки
innodb_buffer_pool_size = 1G  # Настройте под ваш сервер
innodb_log_file_size    = 256M
innodb_flush_method     = O_DIRECT
```

#### 3.3 Создание пользователей

```sql
-- Создайте пользователей вручную или через скрипт
-- Пример создания пользователя приложения
CREATE USER 'app_user'@'%' IDENTIFIED VIA mysql_native_password USING PASSWORD('AppPass123!');
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER,
      CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, CREATE VIEW,
      SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, EVENT, TRIGGER
ON my_app_db.* TO 'app_user'@'%';

-- Создание пользователя для репликации
CREATE USER 'repl_user'@'%' IDENTIFIED VIA mysql_native_password USING PASSWORD('ReplPass123!');
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'%';

FLUSH PRIVILEGES;
```

### Шаг 4: Импорт данных

#### Вариант А: mariadb (для стандартного дампа)

```bash
# Импорт данных в MariaDB
mariadb -u root -p < full_dump.sql

# Или с ограничением по времени (для контроля прогресса)
pv full_dump.sql | mariadb -u root -p my_app_db
```

#### Вариант Б: myloader (для mydumper)

```bash
# Восстановление через myloader
myloader \
    --host=target-mariadb \
    --user=root \
    --password=SecurePass123! \
    --threads=8 \
    --directory=/data/migration/dump_2026-08-20 \
    --verbose=3
```

### Шаг 5: Создание пользователей и привилегий

После импорта данных создайте пользователей и права вручную:

```sql
-- Проверка существующих пользователей
SELECT user, host, plugin FROM mysql.user;

-- Создание пользователей (пример скрипта миграции)
-- Сохраните как migrate_users.sql

-- Пользователь приложения
CREATE USER IF NOT EXISTS 'app_user'@'%' IDENTIFIED VIA mysql_native_password USING PASSWORD('new_secure_password');
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER,
      CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, CREATE VIEW,
      SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, EVENT, TRIGGER
ON my_app_db.* TO 'app_user'@'%';

-- Пользователь репликации
CREATE USER IF NOT EXISTS 'repl_user'@'192.168.1.%' IDENTIFIED VIA mysql_native_password USING PASSWORD('repl_password');
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'192.168.1.%';

-- Администратор (осторожно!)
CREATE USER IF NOT EXISTS 'admin'@'localhost' IDENTIFIED VIA ed25519 USING PASSWORD('admin_password');
GRANT ALL PRIVILEGES ON *.* TO 'admin'@'localhost' WITH GRANT OPTION;

FLUSH PRIVILEGES;
```

**Важно:** Пароли в скрипте миграции должны быть новыми. Не используйте пароли из MySQL.

### Шаг 6: Запуск утилиты обновления

Даже после успешного импорта SQL-дампа необходимо обновить системные структуры MariaDB:

```bash
# Обновление системных таблиц
mariadb-upgrade -u root -p

# Проверка завершения
mariadb -e "SELECT VERSION();"
# → result: 12.3.x-MariaDB-...
```

**Примечание:** `mariadb-upgrade` проверит таблицы на совместимость с текущей версией MariaDB и исправит системные представления.

---

## Валидация после миграции

### 1. Проверка объектов

```sql
-- Сравнение количества таблиц
SELECT table_schema, COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
GROUP BY table_schema
ORDER BY table_schema;

-- Проверка хранимых процедур и функций
SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema')
ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME;

-- Проверка триггеров
SELECT TRIGGER_SCHEMA, TRIGGER_NAME, EVENT_OBJECT_TABLE
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema')
ORDER BY TRIGGER_SCHEMA, TRIGGER_NAME;

-- Проверка представлений
SELECT TABLE_SCHEMA, TABLE_NAME
FROM information_schema.VIEWS
WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema')
ORDER BY TABLE_SCHEMA, TABLE_NAME;

-- Проверка событий
SELECT EVENT_SCHEMA, EVENT_NAME, STATUS
FROM information_schema.EVENTS
WHERE EVENT_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema');
```

### 2. Проверка целостности данных

```bash
# Используйте pt-table-checksum из Percona Toolkit (поддерживает MariaDB)
pt-table-checksum --user=admin --password=admin_password \
    --host=target-mariadb \
    --databases=my_app_db \
    --tables=users,orders,products
```

### 3. Проверка производительности

```sql
-- Сравните планы выполнения критичных запросов
EXPLAIN SELECT * FROM my_app_db.users WHERE email = 'test@example.com';

-- Проверьте индексы
SHOW INDEX FROM my_app_db.users;

-- Анализ статистики
ANALYZE TABLE my_app_db.users;
```

### 4. Тестирование приложения

```bash
# Запустите тестовый набор приложения
# Убедитесь, что все функции работают корректно
# Проверьте логи приложения на наличие ошибок
```

---

## Процедура отката (Rollback)

Если миграция не удалась:

1.  **Остановите приложение:** Переключите приложение обратно на MySQL.
2.  **Восстановите MySQL:** Если MySQL не был изменен, просто переключите DNS/IP.
3.  **Если MySQL был изменен:**
    *   Восстановите из бэкапа, созданного перед миграцией.
    *   Переключите приложение на восстановленный MySQL.
4.  **Анализ:** Изучите причины сбоя и скорректируйте план миграции.

---

## Best Practices

### Планирование

1.  **Тестирование:** Всегда тестируйте миграцию в staging среде, идентичной production.
2.  **Документация:** Запишите все действия и их результаты для аудита и повторения.
3.  **Коммуникация:** Уведомите команду и заинтересованные стороны о плановом простое.
4.  **Откатный план:** Всегда имейте четкий план отката, включая время, необходимое для восстановления.

### Выполнение

1.  **Пошаговость:** Выполняйте шаги последовательно, не пропуская проверки.
2.  **Валидация между шагами:** После каждого шага проверяйте результат.
3.  **Логирование:** Записывайте все команды и их вывод для анализа.
4.  **Автоматизация:** Используйте скрипты для рутинных операций (создание дампа, импорт), но контролируйте критические шаги вручную.

### После миграции

1.  **Мониторинг:** Усиленно отслеживайте систему в течение 24-48 часов после миграции.
2.  **Оптимизация:** Выполните `ANALYZE TABLE` на крупных таблицах для обновления статистики оптимизатора.
3.  **Документирование:** Запишите дату миграции, пройденные версии и любые возникшие проблемы.
4.  **Отключение отката:** Через 24-48 часов стабильной работы можно удалить резервные копии MySQL (если они хранятся локально).

---

## Edge Cases и особые сценарии

### Большие базы данных (от 500 ГБ)

*   Используйте `mydumper`/`myloader` вместо `mariadb-dump`/`mariadb`.
*   Рассмотрите возможность физической миграции, если версии совместимы.
*   Планируйте окно миграции с учетом времени на создание дампа и его импорт.
*   Используйте сжатие (`--compress` или `--compress-algo=zstd`) для уменьшения размера дампа.

### Хранимые процедуры с MySQL-специфичными функциями

*   Проверьте синтаксис всех хранимых объектов перед миграцией.
*   Замените MySQL-специфичные функции на аналоги MariaDB или пользовательские функции.
*   Используйте `mariadb-dump --routines --events` для экспорта хранимых объектов.

### Триггеры и события

*   Синтаксис триггеров и событий идентичен в MySQL и MariaDB.
*   Однако, функции, вызываемые внутри триггеров, могут отличаться.
*   Проверьте триггеры после миграции на тестовых данных.

### Шифрование данных (TDE)

*   Если MySQL использует TDE (Transparent Data Encryption), убедитесь, что MariaDB поддерживает тот же алгоритм шифрования.
*   При необходимости дешифруйте данные перед миграцией и зашифруйте после.

### Репликация после миграции

*   Настройка репликации MySQL -> MariaDB невозможна напрямую.
*   После миграции настройте стандартную MariaDB репликацию (Source-Replica).
*   Подробности см. в **[Настройка репликации MariaDB](../replication/setup_guide.md)**.

---

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 1064 (42000): You have an error in your SQL syntax` | Использование MySQL-специфичных хинтов оптимизатора. | Очистите дамп от хинтов типа `/*+ SET_VAR(...) */`. |
| `Authentication plugin 'caching_sha2_password' cannot be loaded` | Клиент или сервер MariaDB не поддерживает этот плагин. | Измените метод аутентификации на `mysql_native_password` на стороне MySQL перед дампом или пересоздайте пользователей на MariaDB. |
| `Unknown system variable 'innodb_redo_log_capacity'` | Попытка использовать конфиг от MySQL 8.4 на MariaDB. | Удалите/замените переменную в `my.cnf` на совместимую. |
| Ошибки в представлениях (Views) | В MySQL представления могли быть созданы с использованием функций, отсутствующих в MariaDB. | Проверьте `SHOW ERRORS` после `mariadb-upgrade` и пересоздайте проблемные View. |
| `Table 'mysql.user' doesn't exist` | Попытка импорта системных таблиц MySQL в MariaDB. | Используйте флаг `--ignore-table=mysql.*` при создании дампа. |
| Медленный импорт больших таблиц | Отсутствие индексов или первичных ключей. | Создайте индексы после импорта данных. Используйте `mariadb-import` для CSV. |
| `ERROR 1227 (42000): Access denied; you need (at least one of) the SUPER privilege` | Недостаточно прав для выполнения операции. | Убедитесь, что у пользователя миграции есть необходимые привилегии. |
| `ERROR 1045 (28000): Access denied for user` | Неверные учетные данные. | Проверьте пароль и хост. Убедитесь, что пользователь создан в MariaDB. |
| Несовместимость JSON функций | Различия в реализации JSON между MySQL и MariaDB. | Проверьте использование функций `JSON_EXTRACT`, `JSON_SET` и т.д. Замените на совместимые аналоги. |
| Проблемы с Character Set | Различия в наборах символов по умолчанию. | Установите `character_set_server=utf8mb4` и `collation_server=utf8mb4_general_ci` в конфигурации. |

---

## Дополнительная информация

### Валидация после миграции

1.  **Проверка объектов:**
    ```sql
    SELECT table_schema, count(*) FROM information_schema.tables GROUP BY table_schema;
    ```
2.  **Проверка целостности данных:** Сравните контрольные суммы для критически важных таблиц (используйте `pt-table-checksum` из Percona Toolkit, он поддерживает MariaDB).

### Связанные документы

*   **[Обзор MariaDB](../overview.md)** — архитектурные отличия.
*   **[Клиентские утилиты MariaDB](../client_utilities.md)** — описание `mariadb-dump`.
*   **[Zero-Downtime Upgrade](./zero_downtime_upgrade.md)** — как обновлять MariaDB в будущем без простоя.
*   **[Конфигурация MariaDB](../configuration.md)** — настройка параметров сервера.
*   **[Резервное копирование MariaDB](../backup_and_recovery.md)** — методы создания резервных копий.
*   **[Настройка репликации MariaDB](../replication/setup_guide.md)** — пошаговое руководство.
*   **[Безопасность MariaDB](../security/index.md)** — настройка аудита и контроля доступа.

### См. также

*   **[Движки хранения MariaDB](../storage_engines.md)** — особенности InnoDB, MyRocks и других движков.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — архитектура Galera и логика кворума.
*   **[Мониторинг MariaDB](../monitoring.md)** — отслеживание метрик через Prometheus.
*   **[MariaDB MaxScale](../MaxScale/maxscale_overview.md)** — прокси-сервер для маршрутизации трафика.
*   **[Официальная документация MariaDB](https://mariadb.com/kb/en/migrating-from-mysql/)** — актуальные инструкции по миграции.
